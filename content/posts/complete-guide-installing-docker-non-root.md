---
title: "Complete Guide: Installing Docker on Linux with Non-Root Access"
date: 2025-01-06
categories: [Docker, Linux, Tutorial]
tags: [docker, linux, non-root, installation, guide]
author: gnolasco
---

---


Docker simplifies application deployment with containerization. Running Docker without root enhances security and streamlines workflows. This guide will walk you through installing Docker on Linux and configuring it for non-root usage.

---


## Prerequisites

- A Linux system (Ubuntu, Debian, CentOS, etc.)
- A user account with `sudo` privileges.

---

## 1. Update Your System

Keeping your system updated ensures compatibility and security.

For **Ubuntu/Debian**:
```bash
sudo apt update && sudo apt upgrade -y
```

For **RHEL-based systems (e.g., CentOS)**:
```bash
sudo yum update -y
```

---

## 2. Install Docker

Docker installation steps vary slightly between Linux distributions.

### For Ubuntu/Debian

1. **Install prerequisite packages**:
   ```bash
   sudo apt install -y apt-transport-https ca-certificates curl software-properties-common
   ```

2. **Add Docker’s official GPG key**:
   ```bash
   curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
   ```

3. **Set up the Docker repository**:
   ```bash
   echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
   ```

4. **Install Docker**:
   ```bash
   sudo apt update
   sudo apt install -y docker-ce docker-ce-cli containerd.io
   ```

### For RHEL/CentOS

1. **Install prerequisite packages**:
   ```bash
   sudo yum install -y yum-utils
   ```

2. **Set up the Docker repository**:
   ```bash
   sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
   ```

3. **Install Docker**:
   ```bash
   sudo yum install -y docker-ce docker-ce-cli containerd.io
   ```

---

## 3. Start and Enable Docker

Start the Docker service:
```bash
sudo systemctl start docker
```

Enable Docker to start on boot:
```bash
sudo systemctl enable docker
```

---

## 4. Verify Docker Installation

Run a test to confirm Docker is installed correctly:
```bash
sudo docker run hello-world
```

You should see a message indicating Docker is running successfully.

---

## 5. Configure Docker for Non-Root Usage

To run Docker commands without `sudo`, follow these steps:

1. **Add your user to the Docker group**:
   ```bash
   sudo usermod -aG docker $USER
   ```

2. **Log out and log back in** for the group changes to apply.

3. **Verify non-root access**:
   ```bash
   docker run hello-world
   ```

If the command runs successfully, Docker is now configured for non-root usage.

---

## Additional Tips

- **Check Docker Version**:
   ```bash
   docker --version
   ```

- **Manage Docker as a Service**:
   - Restart Docker: `sudo systemctl restart docker`
   - Stop Docker: `sudo systemctl stop docker`

- **Uninstall Docker (if needed)**:
   For Ubuntu/Debian:
   ```bash
   sudo apt remove -y docker-ce docker-ce-cli containerd.io
   ```
   For RHEL/CentOS:
   ```bash
   sudo yum remove -y docker-ce docker-ce-cli containerd.io
   ```

---

## Conclusion

Congratulations! Docker is now installed on your Linux system and can be used without root privileges. Enjoy secure and efficient containerized application development! 🚀

---

For more tutorials and guides, stay tuned to this blog. Have questions? Drop them in the comments below!
