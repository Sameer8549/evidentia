import { useState, useEffect } from "react"
import { useParams, Link } from "react-router-dom"
import { Download, AlertTriangle, CheckCircle2, XCircle, FileText, Hash, Clock, FileKey, Shield } from "lucide-react"
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from "@/components/ui"
import type { EvidenceReceipt, EvidenceRecord, MatchedQuote } from "@/lib/api"
import { ApiClient } from "@/lib/api"

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case 'SUPPORTED_TEXT': return <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" /> Supported</Badge>
    case 'UNVERIFIED': return <Badge variant="secondary"><AlertTriangle className="mr-1 h-3 w-3 text-muted-foreground" /> Unverified</Badge>
    case 'REVIEW_REQUIRED': return <Badge variant="warning"><AlertTriangle className="mr-1 h-3 w-3" /> Review Required</Badge>
    case 'VERIFICATION_FAILED': return <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" /> Failed</Badge>
    case 'PASS': return <Badge variant="success"><CheckCircle2 className="mr-1 h-3 w-3" /> Pass</Badge>
    case 'FAIL': return <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" /> Fail</Badge>
    case 'INCONCLUSIVE': return <Badge variant="warning">Inconclusive</Badge>
    default: return <Badge variant="outline">{status}</Badge>
  }
}

function BoundingBoxDisplay({ quote }: { quote: MatchedQuote }) {
  if (!quote.bounding_boxes || quote.bounding_boxes.length === 0) return null
  return (
    <div className="mt-2 text-xs font-mono text-muted-foreground bg-muted/30 p-2 rounded border">
      <span className="text-foreground/70 block mb-1">OCR Match Coordinates:</span>
      {quote.bounding_boxes.map((box, i) => (
        <div key={i}>Page {quote.page_index} [x:{box.x.toFixed(1)}, y:{box.y.toFixed(1)}, w:{box.width.toFixed(1)}, h:{box.height.toFixed(1)}]</div>
      ))}
    </div>
  )
}

export function Receipt() {
  const { id } = useParams()
  const [receipt, setReceipt] = useState<EvidenceReceipt | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    ApiClient.getReceipt(id)
      .then(setReceipt)
      .catch(err => setError(err.response?.data?.detail || err.message || "Failed to load receipt."))
  }, [id])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
        <AlertTriangle className="h-12 w-12 text-destructive" />
        <h2 className="text-xl font-bold">Error Loading Receipt</h2>
        <p className="text-muted-foreground">{error}</p>
        <Button variant="outline" asChild><Link to="/">Return to Dashboard</Link></Button>
      </div>
    )
  }

  if (!receipt) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  // Group facts
  const groupedFacts = receipt.extracted_facts.reduce((acc, fact) => {
    if (!acc[fact.fact_type]) acc[fact.fact_type] = []
    acc[fact.fact_type].push(fact)
    return acc
  }, {} as Record<string, EvidenceRecord[]>)

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `evidentia_receipt_${receipt.metadata.receipt_id}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-10">
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight">Evidence Receipt</h1>
            <Badge variant={receipt.global_status === 'COMPLETED' ? 'success' : 'warning'} className="uppercase">
              {receipt.global_status}
            </Badge>
          </div>
          <p className="text-muted-foreground mt-2 max-w-2xl text-balance">
            Immutable JSON record of semantic extraction and deterministic verification.
          </p>
        </div>
        <Button onClick={downloadJson} variant="outline" className="shrink-0 bg-background">
          <Download className="mr-2 h-4 w-4" /> Download JSON
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center"><FileText className="mr-2 h-4 w-4" /> Document Context</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <h4 className="text-sm font-medium mb-1">Purpose</h4>
              <p className="text-sm text-muted-foreground">{receipt.document_purpose}</p>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-1">Summary</h4>
              <p className="text-sm text-muted-foreground leading-relaxed">{receipt.document_summary}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center"><FileKey className="mr-2 h-4 w-4" /> Source Metadata</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 gap-3 text-sm">
              <div className="flex flex-col">
                <dt className="text-muted-foreground flex items-center"><Hash className="mr-1 h-3 w-3" /> SHA-256</dt>
                <dd className="font-mono text-xs break-all mt-0.5">{receipt.metadata.source_sha256}</dd>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col">
                  <dt className="text-muted-foreground">Original File</dt>
                  <dd className="font-medium truncate">{receipt.metadata.filename}</dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-muted-foreground">Content Type</dt>
                  <dd className="font-medium">{receipt.metadata.file_type}</dd>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col">
                  <dt className="text-muted-foreground flex items-center"><Clock className="mr-1 h-3 w-3" /> Schema Version</dt>
                  <dd className="font-medium">{receipt.schema_version}</dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-muted-foreground">Vision Model</dt>
                  <dd className="font-medium">{receipt.processing.model_tag}</dd>
                </div>
              </div>
            </dl>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-6">
        <h3 className="text-xl font-bold border-b pb-2">Extracted Evidence</h3>
        
        {Object.entries(groupedFacts).length === 0 ? (
          <div className="text-center p-8 border rounded-lg bg-muted/20 text-muted-foreground">
            No semantic facts were extracted from this document.
          </div>
        ) : (
          Object.entries(groupedFacts).map(([type, facts]) => (
            <div key={type} className="space-y-3">
              <h4 className="font-medium capitalize text-primary">{type.replace(/_/g, ' ')}</h4>
              <div className="space-y-3">
                {facts.map((fact, i) => (
                  <Card key={i} className="overflow-hidden">
                    <div className="flex flex-col md:flex-row">
                      <div className="p-4 flex-1">
                        <div className="flex items-start justify-between gap-4 mb-2">
                          <span className="font-semibold text-base">{fact.candidate_value}</span>
                          <StatusBadge status={fact.status} />
                        </div>
                        {fact.original_quotation && (
                          <div className="mt-3">
                            <span className="text-xs text-muted-foreground uppercase font-semibold tracking-wider">Candidate Quotation</span>
                            <blockquote className="mt-1 border-l-2 border-primary/50 pl-3 py-1 text-sm text-muted-foreground italic">
                              "{fact.original_quotation}"
                            </blockquote>
                          </div>
                        )}
                        
                        {fact.matched_quotes && fact.matched_quotes.length > 0 && (
                          <div className="mt-4 pt-4 border-t space-y-3">
                            <span className="text-xs text-muted-foreground uppercase font-semibold tracking-wider block">Verified OCR Matches</span>
                            {fact.matched_quotes.map((quote, j) => (
                              <div key={j} className="bg-muted/30 rounded p-3 text-sm">
                                <p className="font-medium">"{quote.matched_text}"</p>
                                <BoundingBoxDisplay quote={quote} />
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <h3 className="text-xl font-bold flex items-center"><Shield className="mr-2 h-5 w-5" /> Deterministic Checks</h3>
          {receipt.deterministic_checks.length === 0 ? (
            <div className="p-4 border rounded-md text-sm text-muted-foreground">No checks configured.</div>
          ) : (
            <div className="space-y-3">
              {receipt.deterministic_checks.map((check, i) => (
                <Card key={i}>
                  <div className="p-4 flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{check.check_name}</span>
                      <StatusBadge status={check.status} />
                    </div>
                    <p className="text-sm text-muted-foreground">{check.message}</p>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <h3 className="text-xl font-bold">Actionable Guidance</h3>
          {receipt.actionable_guidance.length === 0 ? (
            <div className="p-4 border rounded-md text-sm text-muted-foreground">No guidance extracted.</div>
          ) : (
            <div className="space-y-3">
              {receipt.actionable_guidance.map((step, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg border bg-card">
                  <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary text-xs font-bold">
                    {step.step_order}
                  </div>
                  <div className="space-y-1 pt-0.5">
                    <p className="text-sm font-medium">{step.instruction}</p>
                    {step.is_model_suggestion && (
                      <Badge variant="outline" className="text-[10px] uppercase">Model Suggestion</Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      
    </div>
  )
}
