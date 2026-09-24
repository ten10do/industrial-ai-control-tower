import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ApiError } from './api'
import { AppShell } from './AppShell'
import { AuthProvider, RequireAuth } from './auth'
import { ErrorBoundary } from './components'
import {
  ApprovalDetailPage,
  ApprovalsPage,
  AssetsConfigPage,
  ConnectivityPage,
  DeviceDetailPage,
  DevicesPage,
  IncidentDetailPage,
  IncidentsPage,
  LoginPage,
  NotFoundPage,
  ObservabilityPage,
  OverviewPage,
  WorkflowDetailPage,
  WorkOrderDetailPage,
  WorkOrdersPage,
} from './pages'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => count < 2 && (!(error instanceof ApiError) || error.status >= 500),
    },
  },
})

function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="login" element={<LoginPage />} />
              <Route element={<RequireAuth />}>
                <Route element={<AppShell />}>
                  <Route index element={<OverviewPage />} />
                  <Route path="devices" element={<DevicesPage />} />
                  <Route path="devices/:deviceId" element={<DeviceDetailPage />} />
                  <Route path="incidents" element={<IncidentsPage />} />
                  <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
                  <Route path="workflows/:workflowRunId" element={<WorkflowDetailPage />} />
                  <Route path="observability" element={<ObservabilityPage />} />
                  <Route path="connectivity" element={<ConnectivityPage />} />
                  <Route path="assets-config" element={<AssetsConfigPage />} />
                  <Route path="approvals" element={<ApprovalsPage />} />
                  <Route path="approvals/:approvalId" element={<ApprovalDetailPage />} />
                  <Route path="work-orders" element={<WorkOrdersPage />} />
                  <Route path="work-orders/:workOrderId" element={<WorkOrderDetailPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}

export default App
