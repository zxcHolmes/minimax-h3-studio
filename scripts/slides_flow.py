#!/usr/bin/env python
"""JSON -> Studio images/TTS -> smooth slides -> one subtitled MP4.

All intermediate state lives in a hidden resumable cache. Rendering defaults to
H3_DEPLOY_HOST when configured; --local explicitly enables local rendering.
"""
from pathlib import Path
import argparse, concurrent.futures, difflib, hashlib, json, math, os, re, shlex
import shutil, subprocess, sys, time, urllib.request, wave

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    part.replace(path)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]

_TOOLS = {}
def tool(name):
    if name in _TOOLS: return _TOOLS[name]
    candidates=[os.environ.get("STUDIO_"+name.upper()),str(Path(sys.executable).parent/name),shutil.which(name),"/usr/bin/"+name]
    candidates += [str(p) for p in (Path.home()/"miniconda3/envs").glob("*/bin/"+name)]
    for candidate in dict.fromkeys(p for p in candidates if p):
        if Path(candidate).is_file():
            check=subprocess.run([candidate,"-version"],capture_output=True,timeout=5)
            if check.returncode==0: _TOOLS[name]=candidate;return candidate
    raise RuntimeError("No working "+name+" executable; set STUDIO_"+name.upper())
def run(args, **kwargs):
    if args[0] in ("ffmpeg","ffprobe"): args=[tool(args[0]),*args[1:]]
    return subprocess.run(args, check=True, **kwargs)

def probe(path):
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True).stdout)

def settings():
    result = {}
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            match = re.match(r"(?:export\s+)?(H3_[A-Z0-9_]+)=(.*)", line)
            if match: result[match[1]] = match[2].strip().strip("\"'")
    result.update({k:v for k,v in os.environ.items() if k.startswith("H3_")})
    return result

def resolve(base, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path

class Studio:
    def __init__(self, url, cache):
        self.url = url.rstrip("/"); self.cache = cache
        self.file = cache / "state.json"; self.state = read(self.file) if self.file.exists() else {}
    def get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=30) as response: return json.load(response)
    def submit(self, fields, refs=(), media=None):
        key = digest(dict(fields=fields, refs=[str(p) for p in refs], media=str(media)))
        if key in self.state: return key
        command = ["curl", "--fail-with-body", "-sS", "--max-time", "120", self.url + "/api/jobs"]
        for name, value in fields.items(): command += ["--form-string", f"{name}={value}"]
        for ref in refs: command += ["-F", "ref_image=@" + str(ref)]
        if media: command += ["-F", "media=@" + str(media)]
        response = run(command, capture_output=True, text=True)
        job = json.loads(response.stdout)
        if not job.get("id"): raise RuntimeError(job)
        self.state[key] = dict(id=job["id"], fields=fields); save(self.file, self.state)
        return key
    def collect(self, tasks):
        pending = dict(tasks)
        while pending:
            for key, (target, kind) in list(pending.items()):
                if target.exists(): del pending[key]; continue
                job = self.get("/api/jobs/" + self.state[key]["id"])
                if job["status"] in ("queued", "running"): continue
                if job["status"] != "done": raise RuntimeError(f"Studio {job['id']}: {job.get('error') or job['status']}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if kind == "asr": save(target, job["result"]["transcript"])
                else:
                    url = job["picture_url" if kind == "image" else "audio_url"]
                    part = target.with_suffix(target.suffix + ".part")
                    urllib.request.urlretrieve(self.url + url, part); part.replace(target)
                self.state[key]["status"] = "done"; save(self.file, self.state)
                del pending[key]
            if pending:
                print(f"Studio: {len(pending)} pending", flush=True); time.sleep(5)

def prepare(plan, base, cache, api):
    scenes = plan["scenes"]; refs = {}; definitions = plan.get("characters", {})
    def reference(name, stack=()):
        if name in refs: return refs[name]
        if name in stack: raise ValueError("Cyclic character references")
        item = definitions[name]
        if item.get("image"): path = resolve(base, item["image"])
        else:
            parents = [reference(n, stack + (name,)) for n in item.get("characters", [])]
            prompt = item["prompt"] + "\n" + plan.get("style", "")
            path = cache / "images" / (digest(dict(prompt=prompt, refs=[str(x) for x in parents])) + ".png")
            if not path.exists():
                key = api.submit(dict(kind="image", image_model=plan.get("image_model", "qwen-image-21-turbo"), aspect_ratio="image" if parents else plan.get("aspect_ratio", "16:9"), prompt=prompt, seed=plan.get("seed", 42)), parents)
                api.collect({key:(path,"image")})
        if not path.is_file(): raise FileNotFoundError(path)
        refs[name] = path; return path
    tasks = {}; images = []
    for i, scene in enumerate(scenes):
        if scene.get("image"): path = resolve(base, scene["image"])
        else:
            inputs = [reference(name) for name in scene.get("characters", [])]
            if len(inputs) > 4: raise ValueError("At most four Qwen image references")
            fields = dict(kind="image", image_model=plan.get("image_model", "qwen-image-21-turbo"), aspect_ratio="image" if inputs else plan.get("aspect_ratio", "16:9"), prompt=scene["prompt"] + "\n" + plan.get("style", ""), seed=plan.get("seed", 42)+i)
            path = cache / "images" / (digest(dict(fields=fields, refs=[str(x) for x in inputs])) + ".png")
            if not path.exists(): tasks[api.submit(fields, inputs)] = (path,"image")
        images.append(path)
    audio = resolve(base, plan["audio"]) if plan.get("audio") else cache / "narration.wav"
    takes = []
    if not audio.exists():
        paragraphs = []; text = ""
        for scene in scenes:
            line = scene["narration"].strip()
            if text and len(text)+len(line)>700: paragraphs.append(text); text=""
            text += (" " if text else "") + line
        if text: paragraphs.append(text)
        for text in paragraphs:
            if len(text)>4000: raise ValueError("A narration passage exceeds Studio's 4000-character limit")
            fields=dict(kind="speech", audio_model=plan.get("tts_model","qwen3_tts"), speech_mode="generate", language=plan.get("language","en"), voice=plan.get("voice","Ryan"), instruction=plan.get("instruction","Clear, warm documentary narration at a natural steady pace."), prompt=text, seed=plan.get("seed",42))
            path=cache/"audio"/(digest(fields)+".wav");takes.append(path)
            if not path.exists(): tasks[api.submit(fields)] = (path,"speech")
    api.collect(tasks)
    if not audio.exists():
        # Decode first; concatenate PCM once to avoid repeated AAC priming at joins.
        pcm=[]
        for take in takes:
            raw=run(["ffmpeg","-v","error","-i",str(take),"-f","s16le","-ac","1","-ar","24000","pipe:1"],capture_output=True).stdout
            pcm.append(raw)
        with wave.open(str(audio),"wb") as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b"".join(pcm))
    if not all(p.is_file() for p in images): raise RuntimeError("Incomplete image batch")
    return images,audio

def norm(text):
    # ASR commonly writes spoken English years as digits. Compare equivalent
    # spellings before measuring missing speech; keep the same strict thresholds.
    units="zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens="zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
    def small(n):
        if n < 20: return units[n]
        return tens[n//10] + (" " + units[n%10] if n%10 else "")
    def number(match):
        n=int(match[0])
        if n < 100: return small(n)
        if 1100 <= n <= 1999 and n%100:
            return small(n//100)+" "+("oh " if n%100 < 10 else "")+small(n%100)
        return match[0]
    text=re.sub(r"\b\d{1,4}\b",number,text.lower())
    return "".join(re.findall(r"[a-z0-9\u4e00-\u9fff]",text))

def timing(plan, base, cache, api, audio, fps):
    scenes=plan["scenes"];duration=float(probe(audio)["format"]["duration"])
    subtitle=plan.get("subtitles",{"mode":"soft"})
    if subtitle is True: subtitle={"mode":"soft"}
    if not subtitle: subtitle={"mode":"none"}
    caption=resolve(base,subtitle["file"]) if subtitle.get("file") else cache/"captions.srt"
    if all(s.get("frames") for s in scenes) and (caption.exists() or subtitle.get("mode")=="none"):
        return [int(s["frames"]) for s in scenes],caption if caption.exists() else None,subtitle
    raw=resolve(base,plan["alignment"]) if plan.get("alignment") else cache/"alignment.json"
    if not raw.exists():
        fields=dict(kind="asr",audio_model="qwen3_asr",language=plan.get("language","en"),timestamps="word",prompt=plan["title"]+" narration alignment")
        api.collect({api.submit(fields,media=audio):(raw,"asr")})
    words=read(raw)["words"];source="".join(norm(s["narration"]) for s in scenes);actual="";owner=[]
    for i,w in enumerate(words):
        clean=norm(w["text"]);actual+=clean;owner.extend([i]*len(clean))
    match=difflib.SequenceMatcher(None,source,actual,autojunk=False)
    if match.ratio()<.96: raise RuntimeError("Narration differs substantially from script; review the failed take")
    mapping={b.a+n:b.b+n for b in match.get_matching_blocks() for n in range(b.size)}
    anchors=[];cursor=0
    for scene in scenes:
        size=len(norm(scene["narration"]));hit=[mapping[n] for n in range(cursor,cursor+size) if n in mapping]
        if len(hit)<size*.8: raise RuntimeError("Narration passage missing or poorly aligned")
        a,z=owner[min(hit)],owner[max(hit)];anchors.append((words[a]["start"],words[z]["end"]));cursor+=size
    boundaries=[0]+[math.ceil(max(a[1],b[0]-.1)*fps) for a,b in zip(anchors,anchors[1:])]+[math.ceil(duration*fps)]
    frames=[b-a for a,b in zip(boundaries,boundaries[1:])]
    if any(n<2 for n in frames): raise ValueError("Invalid slide timing")
    if subtitle.get("mode")!="none" and not caption.exists():
        def stamp(t):
            n=round(t*1000);return f"{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}"
        cues=[]
        # Restore script punctuation/spelling only after speech completeness has
        # passed. Map each short source phrase onto the measured word timestamps.
        cursor=0
        for scene in scenes:
            tokens=scene["narration"].split()
            for n in range(0,len(tokens),8):
                text=" ".join(tokens[n:n+8]);size=len(norm(text))
                hit=[mapping[k] for k in range(cursor,cursor+size) if k in mapping]
                if not hit: raise RuntimeError("Caption phrase has no aligned speech")
                a=words[owner[min(hit)]]["start"];z=words[owner[max(hit)]]["end"]
                cues.append(f"{len(cues)+1}\n{stamp(a)} --> {stamp(z)}\n{text}\n")
                cursor+=size
        caption.write_text("\n".join(cues),encoding="utf-8")
    return frames,caption if caption.exists() else None,subtitle

def stage_file(source, directory, name):
    destination=directory/name;destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists():
        try: os.link(source,destination)
        except OSError: shutil.copy2(source,destination)
    return str(destination.relative_to(directory.parent))

def encode(job, folder, width, height, fps):
    import cv2,numpy as np
    cv2.setNumThreads(1)
    out=folder/job["output"]
    if out.exists(): return
    image=cv2.imread(str(folder/job["image"]));h,w=image.shape[:2];scale=max(width*2/w,height*2/h)
    image=cv2.resize(image,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_LANCZOS4)
    top=(image.shape[0]-height*2)//2;left=(image.shape[1]-width*2)//2
    image=image[top:top+height*2,left:left+width*2].copy();N=job["frames"]
    part=out.with_name(out.stem+".part.mp4")
    command=[tool("ffmpeg"),"-v","error","-y","-filter_threads","1","-f","rawvideo","-pix_fmt","bgr24","-s",f"{width}x{height}","-r",str(fps),"-i","pipe:0","-an","-c:v","libx264","-preset","veryfast","-crf","17","-pix_fmt","yuv420p","-threads","2",str(part)]
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for frame in range(N):
            u=frame/max(N-1,1);v=u*u*(3-2*u)
            z=(1.02+.045*v) if job["index"]%2==0 else (1.065-.045*v)
            cw=width*2/z;ch=height*2/z
            matrix=np.array([[cw/width,0,(width*2-cw)*.5],[0,ch/height,(height*2-ch)*.5]],dtype=np.float64)
            rendered=cv2.warpAffine(image,matrix,(width,height),flags=cv2.INTER_CUBIC|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REFLECT_101)
            process.stdin.write(rendered.tobytes())
        process.stdin.close();error=process.stderr.read();status=process.wait()
        if status: raise RuntimeError(error.decode(errors="replace")[-1000:])
    except BaseException:
        process.kill();process.wait();raise
    part.replace(out)

def worker(manifest):
    manifest=Path(manifest).resolve();folder=manifest.parent;data=read(manifest)
    width,height=data["size"];fps=data["fps"];items=data["items"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=data.get("workers",2)) as pool:
        futures=[pool.submit(encode,j,folder,width,height,fps) for j in items if not (folder/j["output"]).exists()]
        for i,f in enumerate(concurrent.futures.as_completed(futures),1):
            f.result();print(f"Render {i}/{len(futures)}",flush=True)
    listing=folder/"concat.txt";listing.write_text("\n".join("file '"+str(folder/j["output"]).replace("'","'\\''")+"'" for j in items)+"\n")
    command=["ffmpeg","-v","error","-y","-f","concat","-safe","0","-i",str(listing),"-i",str(folder/data["audio"])]
    caption=data.get("caption");mode=data.get("subtitle_mode","soft")
    if caption and mode=="soft":command +=["-i",str(folder/caption)]
    command +=["-map","0:v:0","-map","1:a:0"]
    if caption and mode=="soft":command +=["-map","2:0","-c:s","mov_text","-metadata:s:s:0","language="+data.get("subtitle_language","eng"),"-metadata:s:s:0","title=English","-disposition:s:0","default"]
    if caption and mode=="burn":command +=["-vf","subtitles="+Path(caption).name,"-c:v","libx264","-preset","veryfast","-crf","17","-threads","2"]
    else:command +=["-c:v","copy"]
    duration=sum(x["frames"] for x in items)/fps
    command +=["-c:a","aac","-b:a","192k","-ar","48000","-af","apad","-t",f"{duration:.8f}","-metadata","title="+data["title"],"-movflags","+faststart",str(folder/"final.mp4")]
    run(command,cwd=folder)
    final=probe(folder/"final.mp4");video=next(s for s in final["streams"] if s["codec_type"]=="video")
    expected=sum(x["frames"] for x in items)
    counted=json.loads(run(["ffprobe","-v","error","-count_frames","-select_streams","v:0","-show_entries","stream=nb_read_frames","-of","json",str(folder/"final.mp4")],capture_output=True,text=True).stdout)
    if int(counted["streams"][0]["nb_read_frames"])!=expected: raise RuntimeError("Final frame count mismatch")
    if (video["width"],video["height"])!=(width,height): raise RuntimeError("Final raster mismatch")
    save(folder/"result.json",dict(frames=expected,duration=duration,size=[width,height],subtitle_streams=sum(s["codec_type"]=="subtitle" for s in final["streams"])))
    print(f"Done: {duration:.2f}s, {expected} frames",flush=True)

def main(planfile, local=False, validate=False):
    planfile=Path(planfile).resolve();base=planfile.parent;plan=read(planfile)
    if not plan.get("scenes") or not plan.get("title"): raise ValueError("title and nonempty scenes required")
    if not all(s.get("narration","").strip() for s in plan["scenes"]): raise ValueError("Each scene requires narration")
    for scene in plan["scenes"]:
        if not scene.get("image") and not scene.get("prompt"): raise ValueError("Each scene requires prompt or image")
    if validate: print(f"Valid plan: {len(plan['scenes'])} scenes");return
    env=settings();host=plan.get("render",{}).get("host","auto")
    if host=="auto": host=env.get("H3_DEPLOY_HOST")
    if not local and not host: raise RuntimeError("Configure H3_DEPLOY_HOST for server rendering, or explicitly pass --local")
    imports=[]
    for scene in plan['scenes']:
        for name in ('image','clip'):
            if scene.get(name): imports.append(resolve(base,scene[name]))
    for name in ('audio','alignment'):
        if plan.get(name): imports.append(resolve(base,plan[name]))
    sub=plan.get('subtitles')
    if isinstance(sub,dict) and sub.get('file'): imports.append(resolve(base,sub['file']))
    fingerprint={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in imports if p.exists()}
    cache=base/'.slides-cache'/digest(dict(plan=plan,files=fingerprint));cache.mkdir(parents=True,exist_ok=True)
    url=plan.get("studio_url") or env.get("H3_API") or "http://"+env["H3_DEPLOY_HOST"].split("@")[-1]+":"+env.get("H3_PORT","8190")
    api=Studio(url,cache);images,audio=prepare(plan,base,cache,api);fps=plan.get("fps",30)
    frames,caption,subtitle=timing(plan,base,cache,api,audio,fps);assets=cache/"assets";assets.mkdir(exist_ok=True);items=[]
    for i,(scene,image,count) in enumerate(zip(plan["scenes"],images,frames)):
        identity=digest(dict(image=hashlib.sha256(image.read_bytes()).hexdigest(),frames=count,index=i,backend="subpixel_affine_cubic_v2",size=plan.get("size",[1920,1080]),fps=fps))
        output="clip-"+identity+".mp4"
        if scene.get("clip") and resolve(base,scene["clip"]).exists():
            stage_file(resolve(base,scene["clip"]),assets,output);output="assets/"+output
        else: output=output
        picture=stage_file(image,assets,"image-"+identity+image.suffix)
        items.append(dict(index=i,image=picture,frames=count,output=output))
    manifest=dict(title=plan["title"],size=plan.get("size",[1920,1080]),fps=fps,workers=1 if local else plan.get("render",{}).get("workers",4),items=items,audio=stage_file(audio,assets,"narration.wav"),caption=stage_file(caption,assets,"captions.srt") if caption else None,subtitle_mode=subtitle.get("mode","soft"),subtitle_language=subtitle.get("language","eng"))
    # Keep burn-in paths simple for ffmpeg's subtitle filter parser.
    if caption:
        if caption.resolve() != (cache/"captions.srt").resolve():
            shutil.copy2(caption,cache/"captions.srt")
        manifest["caption"]="captions.srt"
    save(cache/"render.json",manifest)
    output=resolve(base,plan.get("output",planfile.stem+".mp4"));output.parent.mkdir(parents=True,exist_ok=True)
    if local:
        os.nice(10);worker(cache/"render.json");shutil.copy2(cache/"final.mp4",output)
    else:
        home=run(["ssh","-o","BatchMode=yes",host,'printf "%s" "$HOME"'],capture_output=True,text=True).stdout
        remote=home+"/.cache/studio-slides/"+digest(plan)
        run(["ssh",host,"mkdir -p "+shlex.quote(remote)])
        run(["rsync","-a","--partial",str(cache)+"/",host+":"+remote+"/"])
        run(["scp","-q",str(Path(__file__).resolve()),host+":"+remote+"/flow.py"])
        command="nice -n 10 "+shlex.quote(home+"/miniconda3/bin/python")+" "+shlex.quote(remote+"/flow.py")+" --worker "+shlex.quote(remote+"/render.json")
        run(["ssh",host,command])
        run(["scp","-q",host+":"+remote+"/final.mp4",str(output)])
        run(["scp","-q",host+":"+remote+"/result.json",str(cache/"result.json")])
    print("OUTPUT:",output,flush=True)

def add_translations(planfile, translationsfile):
    """Add a translated soft track by stream-copying the delivered film."""
    planfile=Path(planfile).resolve();base=planfile.parent;plan=read(planfile)
    translated=read(translationsfile);episode=plan.get("episode","E004")
    lines=translated["episodes"][episode]
    if len(lines)!=len(plan["scenes"]): raise ValueError("One translation per scene is required")
    video=resolve(base,plan.get("output",planfile.stem+".mp4"))
    candidates=[]
    for manifest in (base/".slides-cache").glob("*/render.json"):
        data=read(manifest)
        if data.get("title")==plan["title"] and len(data["items"])==len(lines):
            candidates.append((manifest,data))
    if not candidates: raise RuntimeError("No completed timeline for translated subtitles")
    manifest,data=max(candidates,key=lambda item:item[0].stat().st_mtime)
    cache=manifest.parent;fps=data["fps"];cues=[];frame=0
    def stamp(t):
        n=round(t*1000);return f"{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}"
    for text,item in zip(lines,data["items"]):
        # Keep translated captions readable without changing any audio or frames.
        parts=re.findall(r"[^，。；！？]+[，。；！？]?",text.strip())
        chunks=[];chunk=""
        for part in parts:
            if chunk and len(chunk)+len(part)>44: chunks.append(chunk);chunk=""
            while len(part)>44:
                if chunk: chunks.append(chunk);chunk=""
                chunks.append(part[:44]);part=part[44:]
            chunk+=part
        if chunk: chunks.append(chunk)
        if not chunks: raise ValueError("Empty translated caption")
        start=frame/fps;frame+=item["frames"];end=frame/fps
        total=sum(len(c) for c in chunks);position=start
        for n,chunk in enumerate(chunks):
            stop=end if n==len(chunks)-1 else position+(end-start)*len(chunk)/total
            if len(chunk)>24:
                split=math.ceil(len(chunk)/2);chunk=chunk[:split]+"\n"+chunk[split:]
            cues.append(f"{len(cues)+1}\n{stamp(position)} --> {stamp(stop)}\n{chunk}\n")
            position=stop
    caption=cache/"translation.srt";caption.write_text("\n".join(cues),encoding="utf-8")
    before=probe(video);language=translated.get("language","zho")
    command=["ffmpeg","-v","error","-y","-i",str(video),"-i",str(caption),"-map","0:v","-map","0:a"]
    existing=[s for s in before["streams"] if s["codec_type"]=="subtitle" and s.get("tags",{}).get("language") not in (language,"zh","chi","zho")]
    for s in existing: command +=["-map",f"0:{s['index']}"]
    command +=["-map","1:0","-c","copy","-c:s","mov_text"]
    for n in range(len(existing)): command +=[f"-disposition:s:{n}","0"]
    n=len(existing)
    command +=[f"-metadata:s:s:{n}","language="+language,f"-metadata:s:s:{n}","title="+translated.get("title","Chinese (Simplified)"),f"-disposition:s:{n}","default","-movflags","+faststart"]
    temporary=cache/"translated.part.mp4";run(command+[str(temporary)])
    after=probe(temporary)
    streams=[s for s in after["streams"] if s["codec_type"]=="subtitle"]
    if len(streams)!=len(existing)+1 or streams[-1].get("tags",{}).get("language")!=language:
        raise RuntimeError("Translated subtitle track verification failed")
    for kind in ("video","audio"):
        a=next(s for s in before["streams"] if s["codec_type"]==kind)
        b=next(s for s in after["streams"] if s["codec_type"]==kind)
        if a.get("nb_frames")!=b.get("nb_frames") or a["codec_name"]!=b["codec_name"]:
            raise RuntimeError("Stream copy changed "+kind)
    temporary.replace(video)
    print("SUBTITLES:",episode,"English + Chinese:",video,flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("plan",nargs="?");parser.add_argument("--worker");parser.add_argument("--local",action="store_true");parser.add_argument("--validate",action="store_true");parser.add_argument("--translations",help="Translated scene captions JSON; reuse an existing final video when present");args=parser.parse_args()
    if args.worker: worker(args.worker)
    elif args.plan:
        plan=read(args.plan);output=resolve(Path(args.plan).resolve().parent,plan.get("output",Path(args.plan).stem+".mp4"))
        if not args.translations or not output.exists(): main(args.plan,args.local,args.validate)
        if args.translations and not args.validate: add_translations(args.plan,args.translations)
    else: parser.error("A plan JSON is required")
