# CareLine phone demo on Render

This deployment runs the existing voice agent and real booking tools against **fictional patients and providers**. It is a synthetic demonstration, not a service for real patient data or clinical use. The Vercel website remains the separate read-only preview.

## What Render creates

The repository-root `render.yaml` Blueprint creates:

| Service | Instance | Purpose |
| --- | --- | --- |
| `careline-booking-api` | Starter, one instance | FastAPI booking tools, protected by a generated service credential |
| `careline-demo-data` | 1 GB persistent disk attached to the API | SQLite database at `/app/data/synthetic/memberguide.db` |
| `careline-voice-agent` | Standard, one instance | LiveKit voice worker, one prewarmed job process |

Both services run in Virginia. Standard is a starting size for a small demo, not a measured capacity guarantee. Check memory/CPU during the first call before increasing traffic. The worker connects outbound to LiveKit; it does not need a public HTTP URL. It calls the API over HTTPS. The Blueprint automatically shares the API hostname and generated agent credential with the worker.

**This is not a free deployment.** Render background workers do not have a free instance option. The SQLite disk also requires a paid API instance. Review the two instance charges and disk charge on Render's creation screen before deploying. LiveKit phone-number, transport and inference charges/credits are separate. A free Render API would sleep after inactivity and cannot retain this SQLite database reliably. No paid resources are created merely by pushing this configuration to GitHub.

References: [free-tier limits](https://render.com/docs/free), [workers](https://render.com/docs/background-workers), [disks](https://render.com/docs/disks), [pricing](https://render.com/pricing), [LiveKit custom hosting](https://docs.livekit.io/deploy/custom/deployments/).

## Deploy from GitHub

1. Sign in to Render and select **New → Blueprint**. Connect `theomthakur/care-line`.
2. Select the branch containing this file. This setup was added on **`feat/workspace-redesign`**; choose that branch unless the changes have subsequently been merged elsewhere. Use `render.yaml` at the repository root as the Blueprint path.
3. Review the proposed services, region and estimated charges. This configuration disables automatic deployments after the initial deploy; later pushes require a manual deploy/sync.
4. Enter these three secret values for `careline-voice-agent`, copied from the **existing CareLine LiveKit project**:

   | Variable | Value |
   | --- | --- |
   | `LIVEKIT_URL` | The project's `wss://…livekit.cloud` URL |
   | `LIVEKIT_API_KEY` | Its API key |
   | `LIVEKIT_API_SECRET` | Its API secret |

   Do not paste the entire `.env.local`, upload local `secrets/`, or put any keys in Vercel browser variables. No separate speech-provider keys are required by the current model presets. Render generates the booking credential; you do not need to copy that manually.
5. Apply the Blueprint. Both services build the existing Dockerfile. Initial dependency/model downloads can take time. The backend seeds fictional records on startup without deleting existing bookings.
6. Wait for the API health check and worker registration. In the worker logs, verify that it connects/registers with LiveKit without authentication or backend errors. Do not publish the demo based on an API health check alone.

If service names are already taken, keep the Blueprint reference names consistent. If `BOOKING_API_HOST` is not populated, set it on the worker to the API's public hostname, for example `careline-booking-api-xxxx.onrender.com`, **without** a scheme or path. The launcher constructs the HTTPS URL. Keep the generated `MEMBERGUIDE_AGENT_KEY` identical on both services when rotating it, then redeploy both.

## Keep the existing phone number

In the same LiveKit project, confirm the existing inbound number **+1 (484) 317-0195** routes to the agent name **`take2-agent`**, matching `AGENT_NAME` in the Blueprint. The Render configuration does not buy a number or change dispatch rules. Using another LiveKit project will not automatically bring the number with it.

Stop any local worker using that same project and agent name during cloud verification; otherwise LiveKit can assign the test call to either worker.

## Verify before sharing

1. Visit `https://<your-api-hostname>/healthz`. Expect `{"status":"ok","mode":"synthetic"}`. This checks backend startup and database access, not voice inference.
2. With all local CareLine processes stopped, call the existing number. Use fictional **Maya Torres**, member-number last four **4417**, birth month **April**, ZIP **10023**.
3. Ask for a primary-care appointment with **Dr. Omar Haddad**, and let the agent check the actual available dates. Do not promise a hardcoded date or time. Confirm only the appointment you intend to create in the demo.
4. Verify the worker logs show successful backend tool calls and a booking confirmation. Make a later call to check the existing appointment, then restart the API and confirm it still exists. Never paste service tokens into screenshots or shared logs.
5. Try a wrong identity response and check that patient/booking information remains unavailable. Run one test caller at a time for the same fictional member; the backend intentionally prevents simultaneous active calls for that member.

The local deployment tests exercise authentication, identity verification and database persistence across app restarts. They do **not** establish that a Render container builds, a phone is routed correctly, or a real model completes a booking. Those require the post-deploy checks above.

## Operating the demo

- Current preset: `budget` through LiveKit Inference. Follow LiveKit usage/credit balances and set account spending controls where available. This change does not add an application-wide billing or call-duration cap. Share the number with selected reviewers first.
- Keep only fictional data in the demo. The public API provides no unauthenticated booking access, and this deployment provisions no operator/admin browser credentials.
- The Vercel preview does not automatically show live phone bookings. Connecting its workspace to the backend would be a separate change with server-side operator authentication.
- One API process and one disk-backed instance preserve the existing write-ordering design. Do not increase Uvicorn workers or API replicas as a scaling shortcut. Larger deployments need a separately designed shared database/concurrency approach.
- No automatic database reset is configured. Booked slots remain booked; do not delete the disk to reset a demonstration. Fresh future slots are added at backend startup, so redeploy the API before a demonstration if it has run for weeks and its seeded schedule has become stale.
- Plan deployments between calls. The worker gets up to 300 seconds before Render terminates it and drains for 240 seconds. Calls longer than that remaining window can be interrupted. The disk-backed API also has brief downtime during a redeploy.
- To stop ongoing compute charges when finished, suspend the worker and API in Render. The persistent disk and LiveKit number can continue to incur charges; review those separately before deleting anything. Deleting the disk deletes its stored demo state.

## Validation and limits of this change

The configuration is checked against Render's published Blueprint JSON schema. The Python suite exercises the existing booking behavior and the new deployment entry points. The Docker daemon was unavailable locally, so a full image build and hosted phone test remain deployment acceptance steps. No Render services or paid resources were provisioned by this code change.
