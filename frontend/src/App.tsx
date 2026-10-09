import { BrowserRouter, Routes, Route, Link } from "react-router-dom"
import { ShieldCheck, Activity, Search, CheckCircle } from "lucide-react"
import { Dashboard } from "@/pages/Dashboard"
import { Inspect } from "@/pages/Inspect"
import { Receipt } from "@/pages/Receipt"
import { Verify } from "@/pages/Verify"

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans selection:bg-primary/30">
      <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="flex items-center space-x-2 font-bold">
            <ShieldCheck className="h-6 w-6 text-primary" />
            <span className="hidden md:inline-block">Evidentia</span>
          </Link>
          <nav className="flex items-center space-x-6 text-sm font-medium">
            <Link to="/" className="flex items-center space-x-2 text-muted-foreground hover:text-foreground transition-colors">
              <Activity className="h-4 w-4" />
              <span>Dashboard</span>
            </Link>
            <Link to="/inspect" className="flex items-center space-x-2 text-muted-foreground hover:text-foreground transition-colors">
              <Search className="h-4 w-4" />
              <span>Inspect</span>
            </Link>
            <Link to="/verify" className="flex items-center space-x-2 text-muted-foreground hover:text-foreground transition-colors">
              <CheckCircle className="h-4 w-4" />
              <span>Verify</span>
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1 container mx-auto px-4 py-8">
        {children}
      </main>
      <footer className="py-6 md:px-8 md:py-0 border-t">
        <div className="container mx-auto px-4 flex flex-col items-center justify-between gap-4 md:h-24 md:flex-row">
          <p className="text-balance text-center text-sm leading-loose text-muted-foreground md:text-left">
            Local-first semantic evidence extraction and verification.
          </p>
        </div>
      </footer>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inspect" element={<Inspect />} />
          <Route path="/receipt/:id" element={<Receipt />} />
          <Route path="/verify" element={<Verify />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

export default App
