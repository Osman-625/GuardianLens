-- Supabase Storage buckets for GuardianLens. All buckets are private.
begin;

insert into storage.buckets (id, name, public)
values
    ('listing-images', 'listing-images', false),
    ('reference-corpus', 'reference-corpus', false),
    ('research-images', 'research-images', false),
    ('model-artifacts', 'model-artifacts', false)
on conflict (id) do update set public = false;

drop policy if exists guardianlens_admin_storage_read on storage.objects;
drop policy if exists guardianlens_admin_storage_write on storage.objects;

create policy guardianlens_admin_storage_read
on storage.objects for select to authenticated
using (
    bucket_id in ('reference-corpus', 'research-images', 'model-artifacts')
    and public.is_guardianlens_admin()
);

create policy guardianlens_admin_storage_write
on storage.objects for all to authenticated
using (
    bucket_id in ('reference-corpus', 'research-images', 'model-artifacts')
    and public.is_guardianlens_admin()
)
with check (
    bucket_id in ('reference-corpus', 'research-images', 'model-artifacts')
    and public.is_guardianlens_admin()
);

commit;
