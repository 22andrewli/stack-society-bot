# Discord Review Bot

A Discord bot that allows users to submit reviews for other Discord users using slash commands.

## Features

- `/review` slash command to submit reviews
- Takes a Discord user mention and free text review
- Displays reviews in an embed format

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a Discord Bot:**
   - Go to https://discord.com/developers/applications
   - Create a new application
   - Go to the "Bot" section and create a bot
   - Copy the bot token
   - Enable "Message Content Intent" in the Bot settings
   - Under "Privileged Gateway Intents", enable "Message Content Intent"

3. **Invite the bot to your server:**
   - Go to the "OAuth2" > "URL Generator" section
   - Select "bot" and "applications.commands" scopes
   - Select necessary permissions (Send Messages, Embed Links, etc.)
   - Copy the generated URL and open it in your browser to invite the bot

4. **Set the bot token (choose one method):**
   
   **Method 1: Using a .env file (Recommended - Easiest)**
   
   Create a file named `.env` in the project directory:
   ```
   DISCORD_BOT_TOKEN=your-bot-token-here
   ```
   
   Replace `your-bot-token-here` with your actual bot token from step 2.
   
   **Method 2: Using environment variable**
   
   In your terminal:
   ```bash
   export DISCORD_BOT_TOKEN='your-bot-token-here'
   ```
   
   Note: This only works for the current terminal session. For a permanent solution, use Method 1.

5. **Run the bot:**
   ```bash
   python main.py
   ```

## Usage

Once the bot is running, use the slash command in your Discord server:

```
/review @username "This is a review text"
```

The bot will respond with an embed showing:
- The reviewed user
- The reviewer
- The review text
- Timestamp

## Hosting 24/7

To keep your bot running 24/7, you have several hosting options:

### Option 1: Render (Free Tier Available) ⭐ Recommended for Beginners

1. **Create a Render account** at https://render.com
2. **Create a new Background Worker** (NOT a Web Service):
   - Click "New +" → "Background Worker"
   - Connect your GitHub repository (or use Render's Git integration)
   - Build command: `pip install -r requirements.txt`
   - Start command: `python main.py` (or Render will use your Procfile)
3. **Set environment variables:**
   - In Render dashboard, go to Environment
   - Add `DISCORD_BOT_TOKEN` with your bot token
   - Add `DATABASE_URL` if using a database
4. **Deploy:** Render will automatically deploy and keep your bot running

**Note:** 
- Use "Background Worker" service type, NOT "Web Service" (bots don't need HTTP endpoints)
- Free tier may spin down after inactivity, but will wake up when needed
- Your Procfile should contain: `worker: python main.py`

### Option 2: Railway (Easy Setup)

1. **Create a Railway account** at https://railway.app
2. **Create a new project** and connect your repository
3. **Configure:**
   - Railway auto-detects Python projects
   - Add `DISCORD_BOT_TOKEN` in the Variables section
4. **Deploy:** Railway handles the rest automatically

### Option 3: VPS (DigitalOcean, AWS, etc.)

For more control, use a Virtual Private Server:

1. **Set up a VPS** (Ubuntu recommended)
2. **Install Python and dependencies:**
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip git
   ```
3. **Clone your repository:**
   ```bash
   git clone <your-repo-url>
   cd ss_bot
   pip3 install -r requirements.txt
   ```
4. **Use a process manager (PM2 recommended):**
   ```bash
   # Install PM2
   npm install -g pm2
   
   # Start the bot
   pm2 start main.py --name discord-bot --interpreter python3
   
   # Save PM2 configuration
   pm2 save
   pm2 startup  # Follow instructions to enable auto-start on reboot
   ```

### Option 4: Local Machine (Using PM2)

If you want to run it on your own computer 24/7:

1. **Install PM2:**
   ```bash
   npm install -g pm2
   ```
2. **Start the bot:**
   ```bash
   pm2 start main.py --name discord-bot --interpreter python3
   ```
3. **Useful PM2 commands:**
   ```bash
   pm2 list              # View running processes
   pm2 logs discord-bot  # View logs
   pm2 restart discord-bot  # Restart bot
   pm2 stop discord-bot     # Stop bot
   pm2 delete discord-bot   # Remove from PM2
   ```

### Option 5: systemd (Linux)

For Linux systems, you can create a systemd service:

1. **Create a service file** `/etc/systemd/system/discord-bot.service`:
   ```ini
   [Unit]
   Description=Discord Review Bot
   After=network.target

   [Service]
   Type=simple
   User=your-username
   WorkingDirectory=/path/to/ss_bot
   Environment="DISCORD_BOT_TOKEN=your-token-here"
   ExecStart=/usr/bin/python3 /path/to/ss_bot/main.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

2. **Enable and start the service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable discord-bot
   sudo systemctl start discord-bot
   ```

### Recommended: Render or Railway

For most users, **Render** or **Railway** are the easiest options:
- Free tier available
- Automatic deployments
- Easy environment variable management
- No server maintenance required
