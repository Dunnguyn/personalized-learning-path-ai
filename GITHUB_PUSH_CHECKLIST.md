# 📋 Checklist trước khi Push lên GitHub

## ✅ Chuẩn bị Local Repository

- [ ] **Kiểm tra .env file không được commit**
  ```bash
  git status
  # Không thấy .env trong "Changes to be committed"
  ```

- [ ] **Backend: Xóa __pycache__ folders**
  ```bash
  find . -type d -name __pycache__ -exec rm -r {} +
  find . -type d -name ".pytest_cache" -exec rm -r {} +
  ```

- [ ] **Frontend: Xóa node_modules**
  ```bash
  cd frontend
  rm -rf node_modules
  cd ..
  ```

- [ ] **Frontend: Xóa build folder**
  ```bash
  cd frontend
  rm -rf dist .vite
  cd ..
  ```

- [ ] **Xóa tất cả *.pyc files**
  ```bash
  find . -name "*.pyc" -delete
  ```

## 📝 Cập nhật Documentation

- [ ] **README.md** - Có instructions đầy đủ
- [ ] **.env.example** - Có tất cả variables cần thiết
- [ ] **Backend setup guide** - Clear steps
- [ ] **Frontend setup guide** - Clear steps

## 🔐 Security Check

- [ ] **Không có API keys trong code**
  ```bash
  git grep -i "api_key" -- ':!.gitignore'
  git grep -i "secret" -- ':!.gitignore'
  ```

- [ ] **Không có password hard-coded**

- [ ] **.env không được tracked**
  ```bash
  git rm --cached .env  # Nếu bị commit
  ```

- [ ] **Sensitive files trong .gitignore**
  - `venv/`
  - `.env`
  - `__pycache__/`
  - `node_modules/`
  - `uploads/`

## 📊 Code Quality

- [ ] **Backend không có syntax errors**
  ```bash
  python -m py_compile backend/**/*.py
  ```

- [ ] **Frontend compiled successfully**
  ```bash
  cd frontend
  npm run build
  cd ..
  ```

- [ ] **Không có debug prints**
  ```bash
  git grep "print(" -- ':!.gitignore' | grep -v "logger"
  ```

- [ ] **Không có commented code**

## 🏗️ Project Structure

- [ ] **Folder structure clear**
  ```
  ├── backend/
  ├── frontend/
  ├── .env.example
  ├── .gitignore
  ├── requirements.txt
  └── README.md
  ```

- [ ] **Imports không broken**

- [ ] **Database migrations ready** (nếu có)

## 🧪 Final Testing

- [ ] **Backend starts successfully**
  ```bash
  python -m uvicorn backend.main:app --reload
  # http://localhost:8000 works
  # http://localhost:8000/docs works
  ```

- [ ] **Frontend starts successfully**
  ```bash
  cd frontend && npm run dev
  # http://localhost:5173 works
  ```

- [ ] **Login page loads**

- [ ] **Signup pages load**

- [ ] **API endpoints accessible**

## 📤 Git Preparation

- [ ] **Revert test changes**
  ```bash
  git status
  # Chỉ có legitimate changes
  ```

- [ ] **Create meaningful commit messages**
  ```bash
  git commit -m "feat: Add authentication system with JWT tokens"
  git commit -m "feat: Create signup flow with 2-step process"
  git commit -m "feat: Setup frontend React + Tailwind"
  ```

- [ ] **Check commit history**
  ```bash
  git log --oneline -5
  ```

## 🔄 Before Final Push

```bash
# 1. Stash any uncommitted changes
git stash

# 2. Pull latest from remote
git pull origin main

# 3. Check everything compiles
cd frontend && npm run build && cd ..

# 4. Verify .env is NOT committed
git ls-files | grep ".env"
# Should NOT show .env (only .env.example)

# 5. View what will be pushed
git log origin/main..HEAD

# 6. Final push
git push origin main
```

## ✨ After Push

- [ ] **Verify on GitHub**
  - Check files are there
  - Check .env is NOT visible
  - Check README is readable

- [ ] **Share repository link**

- [ ] **Tag release** (optional)
  ```bash
  git tag -a v1.0.0 -m "Initial release"
  git push origin v1.0.0
  ```

## 🛠️ Troubleshooting

### "I accidentally committed .env!"
```bash
git rm --cached .env
git commit --amend --no-edit
git push -f origin main
```

### "node_modules got committed"
```bash
git rm -r --cached frontend/node_modules
echo "node_modules/" >> .gitignore
git add .gitignore
git commit -m "Remove node_modules"
git push origin main
```

### "Large files in commit history"
```bash
# Check file sizes
git ls-files -l | sort -k5 -rn | head -10

# Remove from history
git filter-branch --tree-filter 'rm -f large_file.zip' HEAD
```

---

✅ **Khi tất cả checkboxes được check, ready để push!**
