"""
Base resume in JSON Resume schema format.
This is the canonical source — all tailoring starts from this.
Education ONLY references BITS Pilani.
"""

BASE_RESUME = {
    "basics": {
        "name": "Vatsal Omar",
        "label": "Software Engineer — AI Agents & Distributed Systems",
        "email": "vatsalomar1@gmail.com",
        "phone": "+91 9696139141",
        "url": "https://linkedin.com/in/vatsalomar",
        "summary": (
            "Software engineer with deep expertise in multi-agent AI systems, "
            "LLM orchestration, and full-stack product development. Built production "
            "agentic systems at BLive serving Zomato, TVS, Ather, and Bounce. "
            "Strong background in reinforcement learning (GRPO), multi-provider "
            "LLM integration, and real-time IoT data pipelines."
        ),
        "location": {
            "city": "Bangalore",
            "region": "Karnataka",
            "countryCode": "IN"
        },
        "profiles": [
            {"network": "LinkedIn", "url": "https://linkedin.com/in/vatsalomar"},
            {"network": "GitHub", "url": "https://github.com/vatsalllll"},
            {"network": "LeetCode", "url": "https://leetcode.com/vatsalomar"}
        ]
    },
    "education": [
        {
            "institution": "Birla Institute of Technology and Science (BITS), Pilani",
            "area": "Computer Science",
            "studyType": "Bachelor of Science",
            "startDate": "2023-08",
            "endDate": "2026-07",
            "location": "Pilani, IN"
        }
    ],
    "work": [
        {
            "company": "BLive",
            "position": "Software Development Intern",
            "location": "Bangalore, IN",
            "startDate": "2024-12",
            "endDate": "2025-09",
            "highlights": [
                "Designed and shipped an agentic notification workflow using Firebase Cloud Messaging "
                "and a Python event-processing backend to route SOS alerts, delivery updates, and "
                "anomaly flags to the right operator roles with sub-second latency.",
                "Built a telematics intelligence layer consuming real-time IoT data streams from "
                "connected EVs, applying rule-based and ML-assisted anomaly detection to surface "
                "battery health degradation, SOS events, and route deviation alerts.",
                "Implemented Role-based Access Control (RBAC) system using NestJS + PostgreSQL "
                "with JWT Auth, enforcing scoped permissions for rider, fleet operator, and admin "
                "roles across a production system serving Zomato, TVS, Ather, and Bounce.",
                "Integrated Google Maps with live vehicle markers, geofencing, and dynamic route "
                "overlays on GCP-backed infrastructure, enabling real-time fleet visibility and "
                "route optimization for operations teams.",
                "Profiled and resolved rendering bottlenecks using Flutter DevTools, reducing app "
                "load times by ~25% across two production apps with high-frequency telemetry update cycles.",
                "Built two cross-platform Flutter apps (rider delivery + fleet dashboard) with "
                "shared Dart codebase across Android and Web; used Bloc and Riverpod for high-frequency state management."
            ]
        }
    ],
    "projects": [
        {
            "name": "ChaosOps AI — Multi-Agent Incident Response Simulator",
            "url": "https://github.com/vatsalllll/chaosops-ai",
            "description": (
                "Hierarchical multi-agent system where SRE, Developer, Manager, and Oversight agents "
                "coordinate under partial observability to resolve cascading production failures. "
                "Includes rogue-agent detection, GRPO policy optimization, and deterministic benchmarking."
            ),
            "tech": ["Python", "FastAPI", "TRL/GRPO", "OpenAI", "Anthropic", "Docker"],
            "highlights": [
                "Built LLM-agnostic agent interfaces with function-calling, streaming parsing, retry logic, "
                "and fallback handling across OpenAI, Anthropic Claude, and open-source providers.",
                "Designed rogue-agent detection where Oversight agent infers malicious behavior from telemetry "
                "and communication patterns, enabling detection of AI-induced failures.",
                "Fine-tuned agent policies using GRPO reinforcement learning with reward decomposition "
                "for resolution accuracy and oversight quality — 98 tests, CI-gated across Python 3.10/3.11/3.12.",
                "Implemented deterministic episode replay: (failure_type, seed) uniquely reproduces every "
                "trajectory, locked by a golden-trace integration test.",
                "Trained on Qwen 2.5 0.5B with Unsloth 4-bit LoRA: mean reward improved from −8.87 to +4.29 "
                "across 800 gradient steps with clean cross-zero around step 340."
            ]
        },
        {
            "name": "StrategyVault — AI Trading Strategy Marketplace",
            "url": "https://strategyvault-web.onrender.com",
            "description": (
                "Subscription-based platform where AI generates, validates, and ranks institutional-grade "
                "trading strategies combining Gemini 2.0, Claude, and OpenAI in a multi-model consensus engine."
            ),
            "tech": ["FastAPI", "Next.js 14", "Redis", "PostgreSQL", "Docker", "Gemini 2.0"],
            "highlights": [
                "Built multi-model Swarm consensus engine querying Gemini, OpenAI, and Claude in parallel "
                "to produce BUY/HOLD/REJECT verdicts with 0-100 confidence rankings.",
                "Engineered RBI (Research-Backtest-Implement) agent loop where Gemini 2.0 autonomously "
                "generates, debugs, and iterates backtesting code via structured prompt refinement.",
                "Integrated walk-forward validation, Monte Carlo simulation, and market regime detection "
                "to prevent overfitting; sandboxed execution with Redis caching and rate limiting.",
                "Shipped full-stack: FastAPI backend (249 tests) + Next.js 14 frontend with subscription tiers."
            ]
        },
        {
            "name": "AcordLayer — Self-Hosted Collaboration Platform",
            "url": "https://github.com/vatsalllll/acordlayer_messaging",
            "description": (
                "Self-hosted collaboration platform combining real-time chat, workflow automation, "
                "and AI-driven extensibility — built with Go and React for privacy-conscious teams."
            ),
            "tech": ["Go", "TypeScript", "React", "PostgreSQL", "WebSockets", "Docker"],
            "highlights": [
                "Architected workflow automation layer with no-code and API-based triggers for agentic "
                "task execution, containerized via Docker Compose for on-premises and cloud deployments.",
                "Designed RL-based agent training roadmap using GRPO policy optimization and custom RL Gym "
                "sandbox for training AI-driven workflow agents on simulated workspace interactions.",
                "Built real-time messaging with WebSocket-based communication and threaded channels in Go, "
                "supporting concurrent multi-user collaboration with low-latency message delivery."
            ]
        }
    ],
    "achievements": [
        {
            "title": "Top 8 — OpenEnv AI Hackathon",
            "description": (
                "Ranked top 8 out of 70,000+ developers in India's largest AI hackathon "
                "(Meta × Hugging Face × PyTorch), building RL environments on Meta's OpenEnv. "
                "Evaluated by Meta & Hugging Face engineers; unlocked direct interview opportunity at Meta AI."
            )
        },
        {
            "title": "Intern of the Quarter — BLive",
            "description": "Recognized for technical excellence, ownership, and cross-team collaboration across fleet management and rider delivery platforms."
        },
        {
            "title": "Winner — National AI Hackathon (OpenAI)",
            "description": "Won the national hackathon in collaboration with OpenAI, competing against hundreds of teams."
        }
    ],
    "skills": {
        "languages": ["TypeScript", "Python", "Go", "JavaScript", "Dart", "Java", "C++", "SQL"],
        "frontend": ["React", "Next.js", "Flutter", "Tailwind CSS", "React Native", "GSAP", "React Three Fiber"],
        "backend": ["FastAPI", "NestJS", "Node.js", "Go", "PostgreSQL", "MongoDB", "Redis", "Supabase", "Firebase"],
        "ai_ml": [
            "LLM fine-tuning", "Prompt Engineering", "RAG", "NLP", "GRPO/RL",
            "Multi-agent orchestration", "Function-calling", "OpenAI GPT",
            "Anthropic Claude", "Google Gemini", "TRL", "LangChain"
        ],
        "cloud_infra": [
            "Google Cloud Platform (GCP)", "Docker", "Git", "Vercel",
            "CI/CD", "WebSockets", "JWT Auth", "REST APIs"
        ]
    }
}
