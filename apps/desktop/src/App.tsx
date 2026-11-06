import { Routes, Route, Navigate } from 'react-router-dom'
import { AdminDashboard } from './pages/AdminDashboard'
import { ChatPage } from './pages/ChatPage'

export function App() {
  return (
    <Routes>
      <Route path="/" element={<AdminDashboard />} />
      <Route path="/chat" element={<ChatPage />} />
      <Route path="/chat/:conversationId" element={<ChatPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
