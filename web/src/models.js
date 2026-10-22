// Checkpoint file names are long and share a prefix; this keeps the part that tells them apart.
export function shortModel(name) {
  return (name || '').replace(/^minimax_h3_/, '').replace(/_comfyui_bf16/, '').replace(/\.safetensors$/, '')
}
