import { useState, useEffect } from "react"
import { Link, useNavigate } from "react-router-dom"
import { Activity, ServerCrash, CheckCircle2, XCircle, Search, UploadCloud, Clock } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent, Button, Badge } from "@/components/ui"
import type { HealthResponse, ReadyResponse } from "@/lib/api"
import { ApiClient } from "@/lib/api"

export function Dashboard() {
  const navigate = useNavigate()
  const [live, setLive] = useState<HealthResponse | null>(null)
  const [ready, setReady] = useState<ReadyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<Array<{ id: string, timestamp: number }>>([])

  useEffect(() => {
    async function fetchHealth() {
      try {
        const liveRes = await ApiClient.checkLive()
        setLive(liveRes)
        const readyRes = await ApiClient.checkReady()
        setReady(readyRes)
      } catch (err: any) {
        setError(err.message || "Failed to connect to Evidentia backend.")
      }
    }
    fetchHealth()
    
    // Load recent from local storage
    try {
      const stored = localStorage.getItem("evidentia_recent_jobs")
      if (stored) {
        setRecent(JSON.parse(stored))
      }
    } catch (e) {}
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center space-y-6">
        <div className="bg-destructive/10 p-4 rounded-full">
          <ServerCrash className="h-12 w-12 text-destructive" />
        </div>
        <div className="max-w-md space-y-2">
          <h2 className="text-2xl font-bold tracking-tight">Backend Unavailable</h2>
          <p className="text-muted-foreground">
            {error}
          </p>
          <div className="bg-muted p-4 rounded-md text-left mt-6">
            <p className="text-sm font-mono text-muted-foreground">
              cd backend<br />
              poetry shell<br />
              uvicorn app.main:app --reload
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Evidentia Workspace</h1>
        <p className="text-muted-foreground mt-2">Local-first document intelligence and evidence verification.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center justify-between">
              API Status
              {live ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <Activity className="h-4 w-4 text-muted-foreground animate-pulse" />}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{live ? "Connected" : "Checking..."}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {live ? `Version ${live.version || '1.0'}` : "Awaiting response"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center justify-between">
              Vision Model
              {ready?.checks.ollama_health === "ok" ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-amber-500" />}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{ready?.checks.ollama_health === "ok" ? "Available" : "Unavailable"}</div>
            <p className="text-xs text-muted-foreground mt-1">
              Local Ollama / Gemma 4
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center justify-between">
              OCR Engine
              {ready?.checks.tesseract_health === "ok" ? <CheckCircle2 className="h-4 w-4 text-green-500" /> : <XCircle className="h-4 w-4 text-amber-500" />}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{ready?.checks.tesseract_health === "ok" ? "Available" : "Unavailable"}</div>
            <p className="text-xs text-muted-foreground mt-1">
              Tesseract OCR
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="col-span-1 border-primary/50 shadow-sm">
          <CardHeader>
            <CardTitle>Inspect a Document</CardTitle>
            <CardDescription>
              Upload a PDF or image to extract facts and verify claims.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm space-y-2 text-muted-foreground">
              <div className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-primary" /> OCR processing</div>
              <div className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-primary" /> Vision analysis</div>
              <div className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-primary" /> Evidence matching</div>
              <div className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-primary" /> Immutable receipt generation</div>
            </div>
            <Button className="w-full mt-4" size="lg" onClick={() => navigate("/inspect")}>
              <UploadCloud className="mr-2 h-4 w-4" /> Start Inspection
            </Button>
          </CardContent>
        </Card>

        <Card className="col-span-1">
          <CardHeader>
            <CardTitle>Recent Inspections</CardTitle>
            <CardDescription>
              Previously inspected documents on this device.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {recent.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-muted-foreground text-sm">
                <Search className="h-8 w-8 mb-2 opacity-20" />
                No recent inspections found.
              </div>
            ) : (
              <div className="space-y-3">
                {recent.slice(0, 5).map(r => (
                  <Link to={`/receipt/${r.id}`} key={r.id} className="flex flex-col gap-1 p-3 rounded-md border bg-muted/40 hover:bg-muted transition-colors">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium truncate pr-4">{r.id.split("-")[0]}...{r.id.split("-")[4]}</span>
                      <Badge variant="outline" className="text-[10px]">Receipt</Badge>
                    </div>
                    <div className="flex items-center text-xs text-muted-foreground">
                      <Clock className="mr-1 h-3 w-3" />
                      {new Date(r.timestamp).toLocaleString()}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
