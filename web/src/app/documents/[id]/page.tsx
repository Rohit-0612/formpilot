import { DocumentView } from "./document-view";

export default async function DocumentPage({ params }: PageProps<"/documents/[id]">) {
  const { id } = await params;
  return <DocumentView documentId={id} />;
}
