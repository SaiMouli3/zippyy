import AuditTable from '@/components/AuditTable'
import { Card, PageHeader } from '@/components/ui'

export default function AuditLogs() {
  return (
    <>
      <PageHeader title="Audit logs" subtitle="Every important action: actor, evidence, previous/new state and request/response payloads." />
      <Card><AuditTable showFilter /></Card>
    </>
  )
}
