-- pgvector RAG memory for approval-trained posting suggestions

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.posting_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  transaction_id UUID REFERENCES public.transactions(id) ON DELETE SET NULL,
  fingerprint_id UUID REFERENCES public.transaction_fingerprints(id) ON DELETE SET NULL,
  posting_decision_id UUID REFERENCES public.posting_decisions(id) ON DELETE SET NULL,
  content_text TEXT NOT NULL,
  embedding vector(1536) NOT NULL,
  qb_account_id TEXT NOT NULL,
  qb_account_name TEXT,
  method TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_posting_memory_user
  ON public.posting_memory (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_posting_memory_embedding
  ON public.posting_memory
  USING hnsw (embedding vector_cosine_ops);

ALTER TABLE public.posting_memory ENABLE ROW LEVEL SECURITY;

CREATE POLICY posting_memory_user ON public.posting_memory
  FOR ALL USING (auth.uid() = user_id);

-- Similarity search RPC (cosine distance; threshold is minimum similarity 0-1)
CREATE OR REPLACE FUNCTION public.match_posting_memories(
  query_embedding vector(1536),
  match_user_id UUID,
  match_threshold FLOAT DEFAULT 0.75,
  match_count INT DEFAULT 5
)
RETURNS TABLE (
  id UUID,
  content_text TEXT,
  qb_account_id TEXT,
  qb_account_name TEXT,
  method TEXT,
  similarity FLOAT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    pm.id,
    pm.content_text,
    pm.qb_account_id,
    pm.qb_account_name,
    pm.method,
    1 - (pm.embedding <=> query_embedding) AS similarity
  FROM public.posting_memory pm
  WHERE pm.user_id = match_user_id
    AND 1 - (pm.embedding <=> query_embedding) >= match_threshold
  ORDER BY pm.embedding <=> query_embedding
  LIMIT match_count;
$$;
