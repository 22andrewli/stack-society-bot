# GitHub Actions Deployment Setup

This guide will help you set up automatic deployment from GitHub to your GCP VM.

## Prerequisites

- Your code is in a GitHub repository
- You have SSH access to your GCP VM
- Git is initialized in your `~/ss_bot` directory on the VM

## Step 1: Initialize Git on VM (if not already done)

SSH into your VM and run:

```bash
cd ~/ss_bot
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
# Or if using SSH:
# git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO_NAME.git
```

## Step 2: Create SSH Key Pair for GitHub Actions

On your **local machine** (or VM), generate a new SSH key:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy
```

This creates two files:
- `~/.ssh/github_actions_deploy` (private key) - Keep this SECRET
- `~/.ssh/github_actions_deploy.pub` (public key) - Add to VM

## Step 3: Add Public Key to VM

Copy the **public key** content:

```bash
cat ~/.ssh/github_actions_deploy.pub
```

Then on your **VM**, add it to authorized_keys:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
# Paste the public key content, save and exit
chmod 600 ~/.ssh/authorized_keys
```

## Step 4: Get Your VM's External IP

On your GCP Console:
1. Go to Compute Engine → VM instances
2. Find your VM instance
3. Copy the **External IP** address

## Step 5: Add GitHub Secrets

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add these three secrets:

   **Secret 1: VM_IP**
   - Name: `VM_IP`
   - Value: Your VM's external IP (e.g., `34.123.45.67`)

   **Secret 2: VM_USERNAME**
   - Name: `VM_USERNAME`
   - Value: Your VM username (e.g., `g22andrewh_li`)

   **Secret 3: VM_SSH_KEY**
   - Name: `VM_SSH_KEY`
   - Value: The **entire content** of your private key file:
     ```bash
     cat ~/.ssh/github_actions_deploy
     ```
     Copy everything including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`

## Step 6: Test the Connection

Test SSH from your local machine:

```bash
ssh -i ~/.ssh/github_actions_deploy g22andrewh_li@YOUR_VM_IP
```

If it works, you're good to go!

## Step 7: Push Your Code

Once everything is set up:

```bash
git add .
git commit -m "Add GitHub Actions deployment"
git push origin main
```

## Step 8: Monitor Deployment

1. Go to your GitHub repository
2. Click the **Actions** tab
3. You should see the deployment workflow running
4. Click on it to see the deployment logs

## Troubleshooting

### If deployment fails:

1. **Check GitHub Actions logs** - Click on the failed workflow run to see errors
2. **Test SSH manually** - Make sure the SSH key works
3. **Check VM permissions** - Make sure the user can restart systemd services:
   ```bash
   # On VM, check if user can restart services
   sudo systemctl restart discord-bot
   ```
4. **Check git remote** - Make sure git remote is set correctly on VM:
   ```bash
   cd ~/ss_bot
   git remote -v
   ```

### Common Issues:

- **Permission denied**: Check SSH key permissions and authorized_keys file
- **Git pull fails**: Make sure git is initialized and remote is set
- **Service restart fails**: User might need passwordless sudo for systemctl

### Enable Passwordless Sudo (if needed):

```bash
sudo visudo
# Add this line (replace with your username):
g22andrewh_li ALL=(ALL) NOPASSWD: /bin/systemctl restart discord-bot
```

## Security Notes

- ⚠️ **Never commit your private SSH key to GitHub**
- ⚠️ **Keep your private key secure** - Only add it as a GitHub Secret
- ✅ The private key is stored encrypted in GitHub Secrets
- ✅ Only authorized GitHub Actions can use the key
