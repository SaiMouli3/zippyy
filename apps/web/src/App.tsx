import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout'
import CreateOrder from '@/pages/CreateOrder'
import Orders from '@/pages/Orders'
import ShippingOptions from '@/pages/ShippingOptions'
import OrderDetail from '@/pages/OrderDetail'
import Tracking from '@/pages/Tracking'
import MockControl from '@/pages/MockControl'
import NdrCases from '@/pages/NdrCases'
import NdrCaseDetail from '@/pages/NdrCaseDetail'
import Approvals from '@/pages/Approvals'
import SellerRulesPage from '@/pages/SellerRules'
import CarrierRulesPage from '@/pages/CarrierRules'
import AuditLogs from '@/pages/AuditLogs'
import { Empty, Spinner } from '@/components/ui'

const Dashboard = lazy(() => import('@/pages/Dashboard')) // pulls in the charting library only when needed

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Suspense fallback={<Spinner />}><Dashboard /></Suspense>} />
        <Route path="orders" element={<Orders />} />
        <Route path="orders/new" element={<CreateOrder />} />
        <Route path="orders/:orderId" element={<OrderDetail />} />
        <Route path="orders/:orderId/rates" element={<ShippingOptions />} />
        <Route path="orders/:orderId/tracking" element={<Tracking />} />
        <Route path="mock-carriers" element={<MockControl />} />
        <Route path="ndr" element={<NdrCases />} />
        <Route path="ndr/:caseId" element={<NdrCaseDetail />} />
        <Route path="ndr/:caseId/conversation" element={<NdrCaseDetail initialTab="conversation" />} />
        <Route path="approvals" element={<Approvals />} />
        <Route path="rules/seller" element={<SellerRulesPage />} />
        <Route path="rules/carriers" element={<CarrierRulesPage />} />
        <Route path="audit" element={<AuditLogs />} />
        <Route path="*" element={<Empty title="Page not found" />} />
      </Route>
    </Routes>
  )
}
