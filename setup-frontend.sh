#!/bin/bash

# Frontend Setup Script
# Run this to quickly set up the frontend

echo "🚀 Setting up Personalized Learning Path Frontend"
echo "=================================================="

# Check if Node.js and npm are installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 16 or higher."
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm."
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo "✅ npm version: $(npm --version)"

# Navigate to frontend directory
cd "$(dirname "$0")/frontend"

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
npm install

if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "✅ Dependencies installed successfully!"
echo ""
echo "📝 Next steps:"
echo "  1. Copy .env.example to .env (if not already done)"
echo "  2. Update environment variables in .env if needed"
echo "  3. Run: npm run dev"
echo ""
echo "🌐 The app will be available at http://localhost:5173"
echo ""
echo "🔧 Make sure your backend is running on http://localhost:8000"
