# Image Enhancer API - EC2 Deployment Guide

## Prerequisites

- Ubuntu/Amazon Linux EC2 instance
- Git installed
- Python 3.9+ installed
- Node.js 16+ installed (for PM2)

## Step 1: Connect to EC2

```bash
ssh -i your-key.pem ubuntu@your-ec2-ip
```

## Step 2: Install System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and pip
sudo apt install -y python3 python3-pip python3-venv

# Install Node.js (for PM2)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install PM2 globally
sudo npm install -g pm2
```

## Step 3: Clone Repository

```bash
cd ~
git clone <your-repo-url> Image-Enhancer
cd Image-Enhancer
```

## Step 4: Setup Python Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

## Step 5: Setup Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit with your actual values
nano .env
```

Add your credentials:
```env
STRAPI_API_TOKEN=your-strapi-bearer-token
STRAPI_API_BASE_URL=http://localhost:1338
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=ap-south-1
AWS_BUCKET=your-bucket-name
```

## Step 6: Create Logs Directory

```bash
mkdir -p logs
```

## Step 7: Test the API (Optional)

```bash
# Activate venv and test
source venv/bin/activate
python enhancement_api.py serve 8000

# Press Ctrl+C to stop
```

## Step 8: Start with PM2

```bash
# Start the API
pm2 start ecosystem.config.js

# Check status
pm2 status

# View logs
pm2 logs image-enhancer-api
```

## Step 9: Setup PM2 to Start on Reboot

```bash
# Generate startup script
pm2 startup

# Save current process list
pm2 save
```

## Useful PM2 Commands

```bash
pm2 status                     # Check status
pm2 logs image-enhancer-api    # View logs
pm2 logs image-enhancer-api --lines 100  # View last 100 lines
pm2 restart image-enhancer-api # Restart
pm2 stop image-enhancer-api    # Stop
pm2 delete image-enhancer-api  # Remove from PM2
pm2 monit                      # Monitor dashboard
```

## API Endpoints

Once running, the API is available at `http://your-ec2-ip:8000`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/process/order` | POST | Process order (async, returns immediately) |
| `/process/order-sync` | POST | Process order (sync, waits for completion) |
| `/render/album` | POST | Render album pages |
| `/enhance/album` | POST | Enhance album images |

### Example API Call

```bash
curl -X POST http://localhost:8000/process/order \
  -F "order_id=your-order-id"
```

## Security Group Configuration

Make sure your EC2 security group allows:
- Inbound: Port 8000 (or your chosen port) from your IP/VPC
- Outbound: All traffic (for S3 uploads and external API calls)

## Updating the Application

```bash
cd ~/Image-Enhancer

# Pull latest changes
git pull origin main

# Activate venv and update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart PM2
pm2 restart image-enhancer-api
```

## Troubleshooting

### Check logs for errors
```bash
pm2 logs image-enhancer-api --lines 200
```

### Check if port is in use
```bash
sudo lsof -i :8000
```

### Restart if stuck
```bash
pm2 delete image-enhancer-api
pm2 start ecosystem.config.js
```

### Check Python version
```bash
python3 --version  # Should be 3.9+
```
