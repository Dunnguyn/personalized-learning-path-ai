# 🐳 Docker Setup Guide

This guide explains how to use Docker and Docker Compose for development and production deployment.

## Overview

The project includes:
- **Backend** - FastAPI with multi-stage build
- **Frontend** - React/Vite with hot reload
- **MongoDB** - Database with persistence
- **Redis** - Optional caching layer
- **Mongo Express** - Optional MongoDB UI for development

## 📋 Prerequisites

- **Docker** >= 20.10
- **Docker Compose** >= 2.0
- **4GB RAM** minimum
- **.env** file with configuration (copy from `.env.example`)

## 🚀 Quick Start

### 1. Setup Environment File

```bash
cp .env.example .env
```

Edit `.env` and set:
```env
MONGO_USERNAME=mongodb
MONGO_PASSWORD=your_secure_password
GEMINI_API_KEY=your_api_key
SECRET_KEY=your_secret_key_32_chars
```

### 2. Start All Services

```bash
# Start all services with hot reload (development)
docker-compose up

# OR start in background
docker-compose up -d

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f mongodb
```

### 3. Access Services

```
Frontend:       http://localhost:5173
Backend API:    http://localhost:8000
API Docs:       http://localhost:8000/api/docs
MongoDB:        mongodb://localhost:27017
MongoDB UI:     http://localhost:8081 (optional, dev profile)
Redis:          redis://localhost:6379
```

### 4. Stop Services

```bash
# Stop all services (keep data)
docker-compose stop

# Stop and remove all (clear data)
docker-compose down

# Remove all including volumes (dangerous!)
docker-compose down -v
```

## 🔧 Advanced Usage

### Run with MongoDB UI (Development Only)

```bash
# Include dev profile to start mongo-express
docker-compose --profile dev up
```

Then access MongoDB UI at: http://localhost:8081

`Username: admin` `Password: admin`

### Rebuild Images

```bash
# Rebuild backend after code changes
docker-compose build backend

# Rebuild all images
docker-compose build

# Rebuild without cache
docker-compose build --no-cache
```

### Run Commands in Containers

```bash
# Backend bash shell
docker-compose exec backend bash

# Run Python command
docker-compose exec backend python -m pytest

# Frontend bash shell
docker-compose exec frontend sh

# Run npm command
docker-compose exec frontend npm run build
```

### View Container Stats

```bash
# Monitor real-time stats
docker stats

# Check specific container
docker stats learning_path_backend
```

## 📦 Production Deployment

### Build Production Images

```bash
# Build backend production image
docker build -t learning-path-backend:1.0.0 .

# Tag for registry
docker tag learning-path-backend:1.0.0 registry.example.com/learning-path-backend:1.0.0

# Push to registry
docker push registry.example.com/learning-path-backend:1.0.0
```

### Production Docker Compose

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'
services:
  backend:
    image: learning-path-backend:1.0.0
    environment:
      ENVIRONMENT: production
      DEBUG: 'false'
    restart: always
    # Add more production configs
```

Run with:
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Database Backup

```bash
# Backup MongoDB
docker-compose exec mongodb mongodump --out /backup

# Restore MongoDB
docker-compose exec mongodb mongorestore /backup
```

## 🔒 Security Best Practices

### Environment Variables
- ✅ Use strong passwords for MongoDB
- ✅ Generate new SECRET_KEY (32+ chars)
- ✅ Never commit `.env` file
- ✅ Use secrets management in production (AWS Secrets Manager, etc)

### Network Security
- ✅ Use internal Docker network only
- ✅ Expose only necessary ports (8000, 5173)
- ✅ Use reverse proxy (nginx) in production
- ✅ Enable HTTPS/TLS

### Container Security
- ✅ Use specific versions, not latest
- ✅ Run as non-root user
- ✅ Limited permissions for volumes
- ✅ Regular security updates

## 🐛 Troubleshooting

### Backend won't connect to MongoDB

```bash
# Check if MongoDB is running and healthy
docker-compose ps

# View MongoDB logs
docker-compose logs mongodb

# Check MongoDB is accepting connections
docker-compose exec mongodb mongosh -u mongodb -p
```

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process or use different port
PORT=8001 docker-compose up -d backend
```

### Permissions Issues with Volumes

```bash
# Fix owner permissions
docker-compose exec backend chown -R 1000:1000 /app/backend/uploads
```

### Out of Disk Space

```bash
# Clean up unused images, containers, volumes
docker system prune -a

# Remove specific orphaned volumes
docker volume prune
```

## 📊 Performance Tuning

### Resource Limits

Edit `docker-compose.yml`:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### Database Optimization

```yaml
mongodb:
  command: mongod --cache.cacheSizeGB 2
```

### Redis Persistence

```yaml
redis:
  command: redis-server --appendonly yes --appendfsync everysec
```

## 📚 Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Best Practices for Writing Dockerfiles](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)

---

**Happy Containerizing! 🚀**
