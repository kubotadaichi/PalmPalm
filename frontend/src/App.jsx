import { useState } from 'react'
import { useSession } from './hooks/useSession'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

export default function App() {
  const [page, setPage] = useState('title')
  const { turn, vadError, timeLeft } = useSession({
    enabled: page === 'session',
  })

  return (
    <div>
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          turn={turn}
          vadError={vadError}
          timeLeft={timeLeft}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </div>
  )
}
