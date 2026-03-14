import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home'
import Preparation from './pages/Preparation'
import FortuneTelling from './pages/FortuneTelling'
import Result from './pages/Result'
import './App.css'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/page2" element={<Preparation />} />
      <Route path="/page3" element={<FortuneTelling />} />
      <Route path="/page4" element={<Result />} />
    </Routes>
  )
}

export default App
