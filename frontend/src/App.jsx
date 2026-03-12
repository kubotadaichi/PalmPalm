import { useState } from 'react'
import { useBackendWS } from './hooks/useBackendWS'
import { VibrationEffect } from './components/VibrationEffect'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

export default function App() {
  const [page, setPage] = useState('title')
  const wsUrl = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
  const httpBase = wsUrl.replace(/^ws/, 'http').replace(/\/ws\/.*$/, '')
  const { agitationLevel, aiText, aiAudioUrl, connected, turn, setTurnToAi } = useBackendWS()

  return (
    <VibrationEffect agitationLevel={agitationLevel}>
      {!connected && (
        <div className="fixed top-2 left-2 text-xs text-yellow-400 z-50 bg-black/50 px-2 py-1 rounded">
          ⚠ Backend未接続
        </div>
      )}
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          agitationLevel={agitationLevel}
          aiText={aiText}
          aiAudioUrl={aiAudioUrl}
          httpBase={httpBase}
          turn={turn}
          setTurnToAi={setTurnToAi}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </VibrationEffect>
  )
}
