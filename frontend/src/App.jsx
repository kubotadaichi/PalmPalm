import { useState } from 'react'
import { useSession } from './hooks/useSession'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

export default function App() {
  const [page, setPage] = useState('title')
  const { aiText, aiAudioQueue, turn, aiTurnEnded, audioPlayedRef, startUserTurn, setTurnToAi, sendAudio } = useSession()

  return (
    <div>
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          aiText={aiText}
          aiAudioQueue={aiAudioQueue}
          audioPlayedRef={audioPlayedRef}
          turn={turn}
          aiTurnEnded={aiTurnEnded}
          startUserTurn={startUserTurn}
          setTurnToAi={setTurnToAi}
          sendAudio={sendAudio}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </div>
  )
}
