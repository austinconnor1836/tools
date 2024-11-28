# dev-tools

A collection of useful utilities for software developers.
It includes commands for:
- git:
  - Create a copy of a git branch
  - Delete all branches except for those specified as arguments

## Getting Started

### Installation

To install and use the `tools` script globally, follow the steps below:

1. **Clone the repository**:

   ```bash
   git clone git@github.com:austinconnor1836/dev-tools.git
2. **Make the `tools` script executable**:
   ```bash
   cd dev-tools
   chmod +x tools
3. **Add the script to your PATH based on which shell you use**:
   - Bash (`~/.bashrc`): 
     ```bash
     echo 'export PATH="$HOME/<YOUR_PATH_TO_DEV_TOOLS_REPO_CLONE>:$PATH"' >> ~/.bashrc
   - Z Shell (`~/.zshrc`):
     ```bash
     echo 'export PATH="$HOME/<YOUR_PATH_TO_DEV_TOOLS_REPO_CLONE>:$PATH"' >> ~/.zshrc
   - Fish Shell (`~/.config/fish/config.fish`):
     ```bash
     echo 'export PATH="$HOME/<YOUR_PATH_TO_DEV_TOOLS_REPO_CLONE>:$PATH"' >> ~/.config/fish/config.fish

## Get Captions of Youtube Video
1. Download cookies
2. With timestamps: `yt-dlp --write-subs --sub-lang en --skip-download --cookies cookies.txt https://youtu.be/MN_rlPb6LRA?si=AghZoqZQF-g8AKYO`


## Using yt-dlp directly
`yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" --merge-output-format mp4 --postprocessor-args "-c:v libx264 -preset slow -crf 23 -c:a aac -b:a 128k" "<YOUTUBE_VIDEO_URL>"`