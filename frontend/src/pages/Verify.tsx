import { useState, useRef } from "react"
import { ShieldCheck, UploadCloud, CheckCircle2, XCircle, AlertTriangle, Loader2 } from "lucide-react"
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter, Button, Input, Label } from "@/components/ui"
import { ApiClient } from "@/lib/api"

export function Verify() {
  const [receiptFile, setReceiptFile] = useState<File | null>(null)
  const [sourceFile, setSourceFile] = useState<File | null>(null)
  
  const [isVerifying, setIsVerifying] = useState(false)
  const [result, setResult] = useState<{ verified: boolean, details: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const receiptRef = useRef<HTMLInputElement>(null)
  const sourceRef = useRef<HTMLInputElement>(null)

  const handleVerify = async () => {
    if (!receiptFile || !sourceFile) return
    setIsVerifying(true)
    setError(null)
    setResult(null)
    
    try {
      const res = await ApiClient.verifyReceipt(receiptFile, sourceFile)
      setResult(res)
    } catch (err: any) {
      setError(err.response?.data?.details || err.response?.data?.detail || err.message || "Verification failed due to a server error.")
    } finally {
      setIsVerifying(false)
    }
  }

  const reset = () => {
    setReceiptFile(null)
    setSourceFile(null)
    setResult(null)
    setError(null)
  }

  return (
    <div className="max-w-2xl mx-auto space-y-8 pb-10">
      <div className="text-center space-y-2">
        <div className="inline-flex items-center justify-center p-3 bg-primary/10 rounded-full mb-4">
          <ShieldCheck className="h-8 w-8 text-primary" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight">Offline Verification</h1>
        <p className="text-muted-foreground">
          Independently cryptographically verify an Evidence Receipt against its source document.
        </p>
      </div>

      {!result && !error ? (
        <Card>
          <CardHeader>
            <CardTitle>Select Verification Files</CardTitle>
            <CardDescription>You need both the generated JSON receipt and the exact original document.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>1. Evidence Receipt (JSON)</Label>
                <div className="flex gap-4 items-center">
                  <Input 
                    ref={receiptRef}
                    type="file" 
                    accept="application/json"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.[0]) setReceiptFile(e.target.files[0])
                    }}
                  />
                  <Button variant="outline" className="w-full justify-start text-muted-foreground" onClick={() => receiptRef.current?.click()}>
                    <UploadCloud className="mr-2 h-4 w-4" /> 
                    {receiptFile ? <span className="text-foreground truncate max-w-[200px]">{receiptFile.name}</span> : "Select receipt.json"}
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                <Label>2. Original Source Document</Label>
                <div className="flex gap-4 items-center">
                  <Input 
                    ref={sourceRef}
                    type="file" 
                    accept=".pdf,image/png,image/jpeg,image/webp"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.[0]) setSourceFile(e.target.files[0])
                    }}
                  />
                  <Button variant="outline" className="w-full justify-start text-muted-foreground" onClick={() => sourceRef.current?.click()}>
                    <UploadCloud className="mr-2 h-4 w-4" /> 
                    {sourceFile ? <span className="text-foreground truncate max-w-[200px]">{sourceFile.name}</span> : "Select original PDF/Image"}
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button 
              className="w-full" 
              size="lg" 
              disabled={!receiptFile || !sourceFile || isVerifying}
              onClick={handleVerify}
            >
              {isVerifying ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Verifying Signatures...</> : 'Verify Receipt Integrity'}
            </Button>
          </CardFooter>
        </Card>
      ) : (
        <Card className={result?.verified ? "border-green-500/50" : "border-destructive/50"}>
          <CardHeader className="text-center pb-2">
            {result?.verified ? (
              <div className="mx-auto bg-green-500/10 p-4 rounded-full w-fit mb-4">
                <CheckCircle2 className="h-10 w-10 text-green-500" />
              </div>
            ) : (
              <div className="mx-auto bg-destructive/10 p-4 rounded-full w-fit mb-4">
                <XCircle className="h-10 w-10 text-destructive" />
              </div>
            )}
            <CardTitle className="text-2xl">
              {result?.verified ? "Verification Successful" : "Verification Failed"}
            </CardTitle>
            <CardDescription>
              {result?.verified 
                ? "The receipt digest matches its contents and the source document hash is authentic." 
                : "The receipt failed cryptographic verification."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="bg-muted p-4 rounded-md overflow-x-auto">
              <pre className="text-xs font-mono leading-relaxed text-muted-foreground whitespace-pre-wrap">
                {result?.details || error}
              </pre>
            </div>
            
            <div className="flex items-start gap-3 p-3 bg-primary/10 rounded-md border border-primary/20 text-sm">
              <AlertTriangle className="h-5 w-5 text-primary shrink-0" />
              <p>
                <strong>Important Note:</strong> A successful integrity result confirms that this JSON receipt was generated for this exact source file and has not been tampered with. It does <em className="italic">not</em> guarantee that all semantic claims within the receipt are factually correct. Always review the "Extracted Evidence" statuses independently.
              </p>
            </div>
          </CardContent>
          <CardFooter>
            <Button variant="outline" className="w-full" onClick={reset}>
              Verify Another Document
            </Button>
          </CardFooter>
        </Card>
      )}
    </div>
  )
}
