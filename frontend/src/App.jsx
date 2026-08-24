import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Home from './pages/Home'
import RAG from './pages/RAG'
import Graph from './pages/Graph'
import Wiki from './pages/Wiki'
import KBManager from './pages/KBManager'
import Models from './pages/Models'
import Monitor from './pages/Monitor'
import Admin from './pages/Admin'

export default function App() {
  return (
    <div className="app-shell">
      <Navbar />
      <main id="main-content" className="main-content" role="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/rag" element={<RAG />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="/wiki" element={<Wiki />} />
          <Route path="/kb" element={<KBManager />} />
          <Route path="/models" element={<Models />} />
          <Route path="/monitor" element={<Monitor />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </main>
    </div>
  )
}