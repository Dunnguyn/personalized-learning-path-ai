# Personalized Learning Path Frontend

React + TypeScript + Tailwind CSS frontend for the AI-powered personalized learning path system.

## 📋 Prerequisites

- Node.js 16+ and npm/yarn/pnpm
- Backend running at `http://localhost:8000`

## 🚀 Quick Start

### 1. Install Dependencies

```bash
npm install
# or
yarn install
# or
pnpm install
```

### 2. Start Development Server

```bash
npm run dev
# or
yarn dev
```

The app will be available at `http://localhost:5173`

### 3. Build for Production

```bash
npm run build
```

## 📁 Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   └── auth/
│   │       └── Login.tsx          # Login page component
│   ├── pages/                      # Page components
│   ├── App.tsx                     # Main app component
│   ├── main.tsx                    # Entry point
│   └── index.css                   # Global styles with Tailwind
├── public/                         # Static assets
├── package.json
├── tsconfig.json
├── tailwind.config.js
├── vite.config.ts
└── index.html
```

## 🎨 Design System

The project uses custom Tailwind colors defined in `tailwind.config.js`:

- **Primary**: `#832e44` (deep rose)
- **Secondary**: `#5b1724` (dark burgundy)
- **Accent**: `#f7dfed` (light pink)
- **Light**: `#fafafa` (off-white)

## 🔌 API Integration

The frontend is configured to proxy API requests to `http://localhost:8000` via Vite's proxy setting. All API calls should use the `/api` prefix:

```typescript
// Example: Making a login request
fetch('/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password })
})
```

## 📝 Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run type-check` - Check TypeScript types
- `npm run lint` - Run ESLint

## 🔐 Authentication

The Login component handles:
- Email/password authentication
- Remember me functionality
- Token storage in localStorage
- Redirect to dashboard on successful login

## 🎯 Next Steps

1. Implement additional pages (Dashboard, Course Content, etc.)
2. Create reusable UI components
3. Set up state management (Redux, Zustand, etc.)
4. Implement API service layer
5. Add authentication context
6. Create protected routes

## 📚 Resources

- [Vite Documentation](https://vitejs.dev/)
- [React Documentation](https://react.dev/)
- [Tailwind CSS Documentation](https://tailwindcss.com/)
- [React Router Documentation](https://reactrouter.com/)
- [TypeScript Documentation](https://www.typescriptlang.org/)
