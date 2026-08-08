<div align="center">
  <img src="https://raw.githubusercontent.com/SriBalaji2112/BRecorder/main/BRecorder/assets/bee_icon.png" alt="BRecorder Logo" width="120" />
  <h1>BRecorder</h1>
  <p><strong>Advanced, High-Performance Screen & Application Recording Engine</strong></p>

  <p>
    <a href="https://github.com/SriBalaji2112/BRecorder/releases">
      <img src="https://img.shields.io/github/v/release/SriBalaji2112/BRecorder?style=flat-square&color=3a7d44" alt="Release" />
    </a>
    <a href="https://github.com/SriBalaji2112/BRecorder/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/SriBalaji2112/BRecorder?style=flat-square&color=blue" alt="License" />
    </a>
    <img src="https://img.shields.io/badge/Platform-Windows-blue?style=flat-square" alt="Platform" />
  </p>
</div>

---

## 🚀 Overview

**BRecorder** is an enterprise-grade, ultra-lightweight desktop and application recording utility built in Python. Powered by a robust FFmpeg backend (`gdigrab`), it is meticulously designed for content creators, software engineers, educators, and enterprise teams who demand zero-lag capturing capabilities combined with state-of-the-art access management.

Gone are the days of bloated recording suites. BRecorder provides exactly what you need in an intuitive, unobtrusive, floating widget architecture that stays out of your way while delivering flawless 1080p 60FPS video.

---

## ✨ Core Features & Real-World Applications

### 🎯 1. Target-Specific Application Recording
**The Feature:** Instead of recording the entire desktop, BRecorder can instantly hook into a specific active window (e.g., Google Chrome, Visual Studio Code) and record *only* that application.
- **Where it's used:** Live coding tutorials, software demonstrations, or confidential presentations.
- **The Advantage:** Eliminates the risk of accidentally leaking sensitive desktop notifications, private messages, or confidential background applications into your final video.

### ⏱️ 2. Intelligent Recurring Timer Alerts
**The Feature:** Set a primary recording time limit (e.g., 60 seconds) with configurable, recurring snooze reminders (e.g., every 10 seconds) that play a discreet audio beep. 
- **Where it's used:** Short-form content creation (TikTok, YouTube Shorts, Reels) and automated QA testing logs.
- **The Advantage:** Keeps you perfectly on script and on time without forcing you to constantly look at a clock. You never overshoot your recording bounds.

### 🔐 3. Remote Hardware Kill-Switch & Access Control
**The Feature:** BRecorder integrates directly with a live GitHub configuration payload. The administrator can instantly revoke access to the application remotely. If the user goes offline, a highly secure 48-hour grace period is activated before a hard lockout.
- **Where it's used:** Enterprise deployment, proprietary software distribution, and managed organizational toolchains.
- **The Advantage:** Guarantees absolute administrative control over who is using the software. You can instantly disable the app across thousands of machines with a single commit.

### 🎛️ 4. Unobtrusive Floating Controller
**The Feature:** Upon starting a session, the main dashboard completely minimizes, leaving a sleek, drag-and-drop floating widget to control your recording.
- **Where it's used:** Intensive gaming sessions, full-screen presentations, and long-form recording.
- **The Advantage:** Provides instant access to Pause/Resume and Stop functions without eating up valuable screen real-estate or cluttering your final recording.

### 🔊 5. Direct System Audio Capture
**The Feature:** Seamlessly captures the internal audio of the machine via the `Stereo Mix` interface, completely bypassing microphone static.
- **Where it's used:** Recording webinars, online meetings, music production, and high-fidelity gameplay.
- **The Advantage:** Ensures crystal clear, lossless audio synchronization directly from the soundcard, free from background room noise.

---

## 🛠️ Technical Architecture

BRecorder is engineered for maximum performance and minimal CPU footprint:

- **GUI Framework:** Built on `PyQt5`, offering hardware-accelerated, modern UI elements with customized dark-mode stylesheets.
- **Encoding Engine:** Leverages `FFmpeg` (`libx264`, `yuv420p` pixel format) running asynchronously in isolated QThreads, ensuring the UI remains 100% responsive.
- **Dynamic Caching:** Implements cache-busting techniques to bypass raw CDN edge caching, ensuring instant remote-control commands.

---

## 📦 Installation & Setup

1. **Download the Setup Executable:**
   Grab the latest `.exe` installer from the [Releases](https://github.com/SriBalaji2112/BRecorder/releases) page.
2. **Run the Installer:**
   Follow the standard Inno Setup wizard. The application will automatically bundle FFmpeg and all required assets.
3. **Launch & Record:**
   Open BRecorder, configure your desired resolution (up to Full Screen) and Frame Rate (up to 60 FPS), and click Start Recording.

---

## 📄 License

This project is licensed under the **MIT License**. See the `LICENSE` file for details. 

*Designed and Developed by Balaji S.*  
*(For enterprise inquiries or support, contact sribalaji2112@gmail.com)*
