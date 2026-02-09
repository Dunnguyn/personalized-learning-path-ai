@echo off
REM Frontend Setup Script for Windows
REM Run this to quickly set up the frontend

echo.
echo 🚀 Setting up Personalized Learning Path Frontend
echo ==================================================
echo.

REM Check if Node.js and npm are installed
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Node.js is not installed. Please install Node.js 16 or higher.
    pause
    exit /b 1
)

where npm >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo ❌ npm is not installed. Please install npm.
    pause
    exit /b 1
)

echo ✅ Node.js version:
node --version
echo ✅ npm version:
npm --version
echo.

REM Navigate to frontend directory
cd /d "%~dp0frontend"

REM Install dependencies
echo 📦 Installing dependencies...
call npm install

if %ERRORLEVEL% NEQ 0 (
    echo ❌ Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ✅ Dependencies installed successfully!
echo.
echo 📝 Next steps:
echo   1. Copy .env.example to .env (if not already done)
echo   2. Update environment variables in .env if needed
echo   3. Run: npm run dev
echo.
echo 🌐 The app will be available at http://localhost:5173
echo.
echo 🔧 Make sure your backend is running on http://localhost:8000
echo.
pause
