-- GuardianLens P-6, FR-11 to FR-14, NFR-05 to NFR-07
begin;

create extension if not exists pgcrypto;

create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    role text not null default 'admin' check (role in ('admin')),
    display_name text,
    created_at timestamptz not null default now()
);

create table if not exists public.sessions (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    user_agent_class text check (user_agent_class in ('mobile', 'tablet', 'desktop'))
);

create table if not exists public.model_bundles (
    id uuid primary key default gen_random_uuid(),
    label text not null unique,
    visual_version text not null,
    textual_version text not null,
    behavioural_version text not null,
    fusion_version text not null,
    calibrator_version text not null,
    band_boundaries jsonb,
    dataset_version text not null,
    seeds jsonb not null,
    category_baselines jsonb not null,
    is_active boolean not null default false,
    created_at timestamptz not null default now(),
    notes text
);

create unique index if not exists model_bundles_one_active_idx
    on public.model_bundles ((is_active)) where is_active = true;

create table if not exists public.assessments (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.sessions(id) on delete cascade,
    platform text not null check (platform in ('mudah', 'carousell', 'other')),
    title_scrubbed text not null,
    description_scrubbed text not null,
    category text not null,
    price numeric(12,2) not null check (price >= 0),
    currency char(3) not null default 'MYR',
    language_detected text not null check (language_detected in ('ms', 'en', 'mixed', 'unsupported')),
    status text not null check (status in ('processing', 'complete', 'failed', 'abandoned')),
    created_at timestamptz not null default now(),
    completed_at timestamptz
);

create index if not exists assessments_session_created_idx
    on public.assessments (session_id, created_at desc);

create table if not exists public.assessment_images (
    id uuid primary key default gen_random_uuid(),
    assessment_id uuid not null references public.assessments(id) on delete cascade,
    storage_path text not null,
    sha256 char(64) not null,
    mime text not null check (mime in ('image/jpeg', 'image/png', 'image/webp')),
    width_px integer not null check (width_px > 0),
    height_px integer not null check (height_px > 0),
    position smallint not null check (position >= 0),
    unique (assessment_id, position)
);

create table if not exists public.seller_features (
    assessment_id uuid primary key references public.assessments(id) on delete cascade,
    account_age_days integer check (account_age_days >= 0),
    rating numeric(3,2) check (rating between 0 and 5),
    review_count integer check (review_count >= 0),
    active_listing_count integer check (active_listing_count >= 0),
    missing_flags jsonb not null
);

create table if not exists public.assessment_results (
    assessment_id uuid primary key references public.assessments(id) on delete cascade,
    model_bundle_id uuid not null references public.model_bundles(id),
    visual_prob real check (visual_prob between 0 and 1),
    textual_prob real check (textual_prob between 0 and 1),
    behavioural_prob real check (behavioural_prob between 0 and 1),
    availability jsonb not null,
    derived_features jsonb not null,
    fused_prob real not null check (fused_prob between 0 and 1),
    risk_score smallint not null check (risk_score between 0 and 100),
    risk_band text not null check (risk_band in ('low', 'moderate', 'high')),
    suggested_checks jsonb not null,
    stage_latency_ms jsonb not null,
    total_latency_ms integer not null check (total_latency_ms >= 0),
    created_at timestamptz not null default now()
);

create table if not exists public.explanations (
    id uuid primary key default gen_random_uuid(),
    assessment_id uuid not null references public.assessments(id) on delete cascade,
    signal text not null check (signal in ('visual', 'textual', 'behavioural')),
    feature_key text not null,
    shap_value real not null,
    direction text not null check (direction in ('raises', 'lowers')),
    template_key text not null,
    display_text text not null,
    rank smallint not null check (rank > 0),
    unique (assessment_id, signal, rank)
);

create table if not exists public.feedback (
    id uuid primary key default gen_random_uuid(),
    assessment_id uuid not null unique references public.assessments(id) on delete cascade,
    verdict text not null check (verdict in ('helpful', 'unclear', 'potentially_incorrect')),
    comment_scrubbed text,
    created_at timestamptz not null default now(),
    updated_at timestamptz
);

create table if not exists public.reference_corpus_images (
    id uuid primary key default gen_random_uuid(),
    storage_path text not null,
    sha256 char(64) not null unique,
    source_note text not null,
    added_by uuid not null references public.profiles(id),
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

create table if not exists public.inference_events (
    id bigint generated always as identity primary key,
    assessment_id uuid not null references public.assessments(id) on delete cascade,
    stage text not null check (stage in ('validate', 'visual', 'textual', 'behavioural', 'fusion', 'explanation', 'persist')),
    status text not null check (status in ('ok', 'error')),
    error_code text,
    duration_ms integer not null check (duration_ms >= 0),
    created_at timestamptz not null default now()
);

create index if not exists inference_events_assessment_idx
    on public.inference_events (assessment_id, created_at);

create table if not exists public.export_log (
    id bigint generated always as identity primary key,
    exported_by uuid not null references public.profiles(id),
    dataset text not null check (dataset in ('outputs', 'study')),
    row_count integer not null check (row_count >= 0),
    created_at timestamptz not null default now()
);

create or replace function public.is_guardianlens_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1 from public.profiles
        where id = auth.uid() and role = 'admin'
    );
$$;

revoke all on function public.is_guardianlens_admin() from public;
grant execute on function public.is_guardianlens_admin() to authenticated;

alter table public.profiles enable row level security;
alter table public.sessions enable row level security;
alter table public.assessments enable row level security;
alter table public.assessment_images enable row level security;
alter table public.seller_features enable row level security;
alter table public.model_bundles enable row level security;
alter table public.assessment_results enable row level security;
alter table public.explanations enable row level security;
alter table public.feedback enable row level security;
alter table public.reference_corpus_images enable row level security;
alter table public.inference_events enable row level security;
alter table public.export_log enable row level security;

revoke all on all tables in schema public from anon, authenticated;
grant select on public.profiles to authenticated;
grant all on public.model_bundles, public.reference_corpus_images, public.export_log to authenticated;
grant usage, select on all sequences in schema public to authenticated;

drop policy if exists profiles_admin_read on public.profiles;
drop policy if exists model_bundles_admin_all on public.model_bundles;
drop policy if exists corpus_admin_all on public.reference_corpus_images;
drop policy if exists export_log_admin_all on public.export_log;

create policy profiles_admin_read on public.profiles
    for select to authenticated using (public.is_guardianlens_admin());
create policy model_bundles_admin_all on public.model_bundles
    for all to authenticated using (public.is_guardianlens_admin()) with check (public.is_guardianlens_admin());
create policy corpus_admin_all on public.reference_corpus_images
    for all to authenticated using (public.is_guardianlens_admin()) with check (public.is_guardianlens_admin());
create policy export_log_admin_all on public.export_log
    for all to authenticated using (public.is_guardianlens_admin()) with check (public.is_guardianlens_admin());

commit;
