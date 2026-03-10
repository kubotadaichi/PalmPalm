import { useState } from 'react'
import { useBackendWS } from './hooks/useBackendWS'
import { VibrationEffect } from './components/VibrationEffect'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

type Page = 'title' | 'rules' | 'session' | 'end'

export default function App() {
  const [page, setPage] = useState<Page>('title')
  const { agitationLevel, aiText, connected } = useBackendWS()

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
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </VibrationEffect>
  )
}
