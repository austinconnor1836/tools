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
     echo 'export PATH="$HOME/scripts:$PATH"' >> ~/.bashrc
   - Z Shell (`~/.zshrc`):
     ```bash
     echo 'export PATH="$HOME/scripts:$PATH"' >> ~/.zshrc
   - Fish Shell (`~/.config/fish/config.fish`):
     ```bash
     echo 'export PATH="$HOME/scripts:$PATH"' >> ~/.zshrc 
   