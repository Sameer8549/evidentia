# Evidentia Frontend

This is the local-first React + Vite frontend for Evidentia, built with TypeScript, Tailwind CSS, and shadcn/ui.

## Prerequisites

- Node.js 18+
- The [Evidentia Backend](../README.md) must be running.

## Environment Variables

By default, the frontend expects the backend API at `http://127.0.0.1:8000`. 
To override this, create a `.env` file in this `frontend` directory:

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Setup and Run

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Start the development server:**
   ```bash
   npm run dev
   ```

3. **Open in browser:**
   Navigate to `http://localhost:5173`.

## Architecture

- **Strictly Local-First**: No external API calls are made except to your configured local Evidentia backend.
- **Polling vs WebSockets**: The dashboard uses lightweight HTTP polling (`GET /api/inspect/{id}/job`) to retrieve progress of the background vision tasks, avoiding stateful WebSocket requirements.
- **Offline Verification**: The verify route submits both the receipt and original source strictly to the local backend's `/api/verify` subprocess validator.

## Build for Production

```bash
npm run build
```
The output will be in the `dist` directory.
