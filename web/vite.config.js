import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// `npm run dev` proxies the API to the deployed server, configured in the repo-root .env.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), 'H3_')
  const host = (env.H3_DEPLOY_HOST || '').split('@').pop()
  const api = env.H3_API || (host ? `http://${host}:${env.H3_PORT || 8190}` : 'http://127.0.0.1:8190')
  return {
    plugins: [vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === 'model-viewer' } } })],
    server: {
      proxy: {
        '/api': api,
        '/files': api,
      },
    },
  }
})
