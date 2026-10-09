import { useState, useRef, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { UploadCloud, AlertCircle, Loader2, ChevronRight, XCircle } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, Button, Badge, Input } from "@/components/ui"
import type { IngestionResponse, JobState } from "@/lib/api"
import { ApiClient } from "@/lib/api"

export function Inspect() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [ingestion, setIngestion] = useState<IngestionResponse | null>(null)
  
  const [job, setJob] = useState<JobState | null>(null)
  
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollTimerRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current)
    }
  }, [])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null)
    const selected = e.target.files?.[0]
    if (!selected) return
    
    // Size check (20MB UI limit - matches backend)
    if (selected.size > 20 * 1024 * 1024) {
      setError("File exceeds 20MB limit.")
      return
    }
    
    setFile(selected)
  }

  const handleUpload = async () => {
    if (!file) return
    setIsUploading(true)
    setError(null)
    
    try {
      const res = await ApiClient.ingestFile(file)
      setIngestion(res)
      
      // Auto start inspection
      const jobRes = await ApiClient.startInspectionJob(res.ingestion_id, true)
      setJob(jobRes)
      
      // Save to recent
      try {
        const stored = localStorage.getItem("evidentia_recent_jobs")
        const recent = stored ? JSON.parse(stored) : []
        localStorage.setItem("evidentia_recent_jobs", JSON.stringify([
          { id: res.ingestion_id, timestamp: Date.now() },
          ...recent.filter((r: any) => r.id !== res.ingestion_id)
        ].slice(0, 10)))
      } catch (e) {}
      
      startPolling(res.ingestion_id)
      
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || "Failed to upload file")
    } finally {
      setIsUploading(false)
    }
  }

  const startPolling = (id: string) => {    
    const poll = async () => {
      try {
        const currentJob = await ApiClient.getInspectionJob(id)
        setJob(currentJob)
        
        if (currentJob.status === "completed" || currentJob.status === "failed") {
          // Polling done
        } else {
          pollTimerRef.current = window.setTimeout(poll, 2000)
        }
      } catch (err: any) {
        setError("Lost connection to job status: " + (err.response?.data?.detail || err.message))
      }
    }
    
    pollTimerRef.current = window.setTimeout(poll, 2000)
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Inspect Document</h1>
        <p className="text-muted-foreground mt-2">Extract facts and match semantic evidence.</p>
      </div>

      {!ingestion && (
        <Card>
          <CardHeader>
            <CardTitle>Upload File</CardTitle>
            <CardDescription>Supported formats: PDF, PNG, JPEG, WEBP. Max size: 20MB.</CardDescription>
          </CardHeader>
          <CardContent>
            <div 
              className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${file ? 'border-primary/50 bg-primary/5' : 'border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/50'}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                const dropped = e.dataTransfer.files?.[0]
                if (dropped) {
                  if (dropped.size > 20 * 1024 * 1024) setError("File exceeds 20MB limit.")
                  else { setError(null); setFile(dropped) }
                }
              }}
            >
              <div className="flex flex-col items-center justify-center space-y-4">
                <div className="bg-muted p-3 rounded-full">
                  <UploadCloud className="h-6 w-6 text-muted-foreground" />
                </div>
                {file ? (
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{file.name}</p>
                    <p className="text-xs text-muted-foreground">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <p className="text-sm font-medium">Drag & drop a file here</p>
                    <p className="text-xs text-muted-foreground">or click to browse</p>
                  </div>
                )}
                <Input 
                  ref={fileInputRef}
                  type="file" 
                  className="hidden" 
                  accept=".pdf,image/png,image/jpeg,image/webp"
                  onChange={handleFileChange}
                />
                <Button variant="secondary" onClick={() => fileInputRef.current?.click()}>
                  Select File
                </Button>
              </div>
            </div>
            
            {error && (
              <div className="mt-4 p-3 bg-destructive/10 border border-destructive/20 rounded-md flex items-start gap-3 text-sm text-destructive">
                <AlertCircle className="h-5 w-5 shrink-0" />
                <p>{error}</p>
              </div>
            )}
          </CardContent>
          <CardFooter className="justify-between border-t p-6">
            <Button variant="ghost" onClick={() => {setFile(null); setError(null)}}>Clear</Button>
            <Button disabled={!file || isUploading} onClick={handleUpload}>
              {isUploading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Uploading...</> : 'Upload & Inspect'}
            </Button>
          </CardFooter>
        </Card>
      )}

      {ingestion && job && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Inspection Job</CardTitle>
                <CardDescription className="truncate max-w-sm mt-1">{ingestion.filename}</CardDescription>
              </div>
              <Badge variant={
                job.status === 'completed' ? 'success' : 
                job.status === 'failed' ? 'destructive' : 'secondary'
              } className="uppercase">
                {job.status === 'completed' && job.stage === 'partial' ? 'PARTIAL' : job.status}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <div className="flex justify-between text-sm mb-1">
                <span className="font-medium capitalize">{job.stage.replace('_', ' ')}</span>
                <span className="text-muted-foreground">{job.progress.pages_processed} / {job.progress.total_pages} pages</span>
              </div>
              <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                <div 
                  className={`h-full transition-all duration-500 ease-in-out ${job.status === 'failed' ? 'bg-destructive' : 'bg-primary'}`}
                  style={{ width: `${Math.max(5, (job.progress.pages_processed / Math.max(1, job.progress.total_pages)) * 100)}%` }}
                />
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4 text-sm bg-muted/40 p-4 rounded-lg border">
              <div>
                <span className="text-muted-foreground block mb-1">Ingestion ID</span>
                <span className="font-mono text-xs">{ingestion.ingestion_id}</span>
              </div>
              <div>
                <span className="text-muted-foreground block mb-1">File Hash (SHA-256)</span>
                <span className="font-mono text-xs truncate block">{ingestion.hash}</span>
              </div>
            </div>

            {job.errors && job.errors.length > 0 && (
              <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-md text-sm text-destructive space-y-2">
                <div className="flex items-center gap-2 font-medium">
                  <XCircle className="h-4 w-4" /> Issues Encountered
                </div>
                <ul className="list-disc pl-5 space-y-1">
                  {job.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
            
            {error && !job.errors?.length && (
              <div className="p-3 bg-destructive/10 border border-destructive/20 rounded-md flex items-start gap-3 text-sm text-destructive">
                <AlertCircle className="h-5 w-5 shrink-0" />
                <p>{error}</p>
              </div>
            )}
          </CardContent>
          
          <CardFooter className="border-t p-6 bg-muted/20">
            {job.receipt_available && (
              <Button className="w-full" onClick={() => navigate(`/receipt/${ingestion.ingestion_id}`)}>
                View Evidence Receipt <ChevronRight className="ml-2 h-4 w-4" />
              </Button>
            )}
            {job.status === 'failed' && (
              <Button className="w-full" variant="outline" onClick={() => {setIngestion(null); setJob(null); setError(null)}}>
                Try Another File
              </Button>
            )}
          </CardFooter>
        </Card>
      )}
    </div>
  )
}
