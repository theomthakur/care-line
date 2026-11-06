# Seminar notes, Fri 6 Nov 2026, 3 PM

Source: speech-to-text of the opening talk, pasted by Om. It is garbled in places, so names and exact numbers below are as heard unless marked.

## Take2
- Builds AI agents for healthcare recruiting. Founders are from Stanford (transcript says "funded by Stanford", likely a mishearing).
- Board advisors: CHROs of large health systems (UCSF, Bon Secours, UNC, Northwell, as heard). Investors include Reach Capital.
- Agents: sourcing, AI interviewer, verifier (license and certification checks), scheduler (live recruiter calendar, rescheduling), sales outreach, and transcript search using vector embeddings.
- Clients as stated: Veterans Affairs and CommonSpirit. Everyone applying for nurse, medical assistant or caregiver roles goes through the system.
- Claimed results (company-stated): about 70 percent of human time saved, about 25 percent lower time to fill within four months at one system, one role staffed in seven days after six months open.
- Values they stressed: 24/7 access, interview within minutes of applying, structured scoring, humans keep the cognitively heavy work, more equitable than resume filters.
- **Hiring across the board:** AE, software engineers, backend, full stack. The event blast also names SWE and FDE fast-track interviews.

## People
- Greg: head of engineering, led the next part of the session.
- Reach Capital partner: the event blast spells her name Jomayra Herrera (the transcript says "Jamar"). Reach invests pre-seed to Series A in learning, healthcare and the future of work. She said her email is her first name at ReachCapital.com. Spelling not confirmed.

## What it means for our project
- Their building blocks are ours: verifier = member verification, scheduler = booking, structured scoring = code-enforced rules.
- Their stated goal, humans keep the judgment work while agents take the admin, is our handoff packet.

## Greg's overview (head of engineering)
- Voice is harder than text for three reasons: latency (people expect a reply in under a second, two seconds at most), turn-taking (knowing a pause means "still thinking"), and audio quality (phone compression and narrowband audio make sounds like S and F merge, plus mumbling and street noise).
- Pipeline: carrier, SIP trunk into a LiveKit room, speech to text, turn detector (now semantic, plus tone and pitch), a small LLM, text to speech in rolling chunks.
- "Within a few minutes of kicking off you will have a deployed voice agent, which you can then customize." Details of the kit were still to come.

## The kit and the rules (from Greg's second half and the repo)
- Repo: github.com/vramesh1/take2-voice-agent-hackathon-starter. Clone, `uv sync`, `lk cloud auth`, `lk app env --write --destination .env.local`, `lk agent console`.
- Scoring weights: 30 job done, 25 difficult caller, 20 natural conversation, 15 clear problem and design choices, 10 bonus. About 10 minutes per team, live.
- Free: $2.50 of inference per person per month, one US number and 50 inbound minutes per account. Hard caps, never charged.
- Default models (budget): AssemblyAI, Gemma 4, Fish Audio. `quality` preset: Deepgram Nova-3, Gemini 3.1 Flash Lite, Cartesia Sonic 3.
- Phone: `lk agent dev --deployment production`, one agent per project, `agent_name` must match the dispatch rule.
- Milestones: 4:00 console, 5:00 talking, 6:00 calling, 7:00 demo-ready.
