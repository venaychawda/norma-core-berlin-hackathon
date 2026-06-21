# NormaCore ElRobot — Project Overview

## What We Built

An **end-to-end AI-powered robotic manipulation system** that enables natural language control of a physical robot arm. A user says "pick up the yellow pen" and the system decomposes, plans, executes, and verifies the task autonomously.

## The Problem

Robotic arms are powerful but require expert programming for every task. Vision-Language-Action (VLA) models can learn tasks from demonstrations, but integrating them into a real-time control stack with monitoring, automation, and a user-friendly interface remains an unsolved engineering challenge.

## Our Solution

A full-stack robotics platform combining:

- **AI Agent (Claude)** — understands natural language, decomposes complex tasks into sub-steps
- **SmolVLA Neural Network** — converts camera images + joint state into motor commands
- **NormaCore Station** — real-time hardware control layer (Rust, 100Hz servo loop)
- **HTTP API** — 24 REST endpoints + WebSocket for real-time state
- **N8N Workflows** — automated monitoring, demo pipelines, and training orchestration
- **Lovable Dashboard** — real-time robot control and monitoring UI

## Key Achievement

From raw hardware to an AI-controlled arm with automated pipelines — built in a hackathon setting on a $220 robot and a Raspberry Pi 5.
