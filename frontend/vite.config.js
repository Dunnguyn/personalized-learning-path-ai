import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
var getPackageName = function (id) {
  var _a;
  var normalizedId =
    (_a = id.split('node_modules/')[1]) === null || _a === void 0 ? void 0 : _a.replace(/\\/g, '/');
  if (!normalizedId) {
    return null;
  }
  var segments = normalizedId.split('/');
  if (segments[0].startsWith('@')) {
    return ''.concat(segments[0], '/').concat(segments[1]);
  }
  return segments[0];
};
// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    strictPort: false,
    // Proxy API requests to backend
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: function (path) {
          return path.replace(/^\/api/, '');
        },
        // Connection pooling and timeouts
        ws: true,
        timeout: 30000,
      },
    },
    // Enable CORS for development
    cors: true,
    // Preload modules for faster HMR
    middlewareMode: false,
  },
  build: {
    // Output directory
    outDir: 'dist',
    // Source map for production debugging (can be disabled for smaller builds)
    sourcemap: false,
    // Use esbuild minification for compatibility with the current Vite version.
    minify: 'esbuild',
    // Chunk size optimization
    rollupOptions: {
      output: {
        manualChunks: function (id) {
          if (!id.includes('node_modules')) {
            return undefined;
          }
          var packageName = getPackageName(id);
          if (!packageName) {
            return undefined;
          }
          if (packageName === 'reactflow' || packageName.startsWith('@reactflow/')) {
            return 'vendor-reactflow';
          }
          if (
            [
              'react-markdown',
              'remark-gfm',
              'remark-parse',
              'remark-rehype',
              'rehype-raw',
              'unified',
            ].includes(packageName) ||
            packageName.startsWith('micromark') ||
            packageName.startsWith('mdast-') ||
            packageName.startsWith('hast-') ||
            packageName.startsWith('unist-') ||
            packageName.startsWith('remark-')
          ) {
            return 'vendor-markdown';
          }
          if (packageName === 'axios') {
            return 'vendor-network';
          }
          if (
            [
              'react',
              'react-dom',
              'react-router',
              'react-router-dom',
              'scheduler',
              'use-sync-external-store',
            ].includes(packageName)
          ) {
            return 'vendor-react';
          }
          return undefined;
        },
        // Asset naming
        assetFileNames: function (assetInfo) {
          var info = assetInfo.name.split('.');
          var ext = info[info.length - 1];
          if (/png|jpe?g|gif|svg/.test(ext)) {
            return 'assets/images/[name]-[hash][extname]';
          } else if (/woff|woff2|eot|ttf|otf/.test(ext)) {
            return 'assets/fonts/[name]-[hash][extname]';
          } else if (ext === 'css') {
            return 'assets/css/[name]-[hash][extname]';
          } else {
            return 'assets/[name]-[hash][extname]';
          }
        },
        // Chunk naming
        chunkFileNames: 'assets/js/[name]-[hash].js',
        // Entry file naming
        entryFileNames: 'assets/js/[name]-[hash].js',
      },
    },
    // Chunk size warnings
    chunkSizeWarningLimit: 500,
    // CSS processing
    cssCodeSplit: true,
    cssMinify: true,
    // Build performance
    reportCompressedSize: true,
    target: 'esnext',
  },
  // Optimization
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'axios'],
    exclude: ['node_modules/.vite'],
  },
  // Environment variables
  define: {
    __DEV__: JSON.stringify(process.env.NODE_ENV === 'development'),
    __PROD__: JSON.stringify(process.env.NODE_ENV === 'production'),
  },
});
