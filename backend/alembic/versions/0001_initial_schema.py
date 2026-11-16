"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-15
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    "companies", "search_keywords", "job_preferences", "resumes", "resume_skills",
    "jobs", "job_matches", "saved_jobs", "application_tracking", "search_history",
    "notification_history", "embedding_cache",
]


def upgrade() -> None:
    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('platform', sa.String(length=30), nullable=False),
    sa.Column('board_token', sa.String(length=200), nullable=False),
    sa.Column('api_region', sa.String(length=10), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_search_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('jobs_collected', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name'),
    sa.UniqueConstraint('platform', 'board_token', name='uq_company_board')
    )
    op.create_table('embedding_cache',
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('model_name', sa.String(length=120), nullable=False),
    sa.Column('dim', sa.Integer(), nullable=False),
    sa.Column('vector', sa.LargeBinary(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('content_hash', 'model_name')
    )
    op.create_table('job_preferences',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('preferred_titles', sa.JSON(), nullable=False),
    sa.Column('preferred_locations', sa.JSON(), nullable=False),
    sa.Column('work_modes', sa.JSON(), nullable=False),
    sa.Column('min_experience', sa.Float(), nullable=True),
    sa.Column('max_experience', sa.Float(), nullable=True),
    sa.Column('employment_types', sa.JSON(), nullable=False),
    sa.Column('salary_min', sa.Integer(), nullable=True),
    sa.Column('salary_max', sa.Integer(), nullable=True),
    sa.Column('salary_currency', sa.String(length=10), nullable=True),
    sa.Column('ai_threshold_enabled', sa.Boolean(), nullable=False),
    sa.Column('ai_threshold', sa.Float(), nullable=False),
    sa.Column('scoring_weights', sa.JSON(), nullable=True),
    sa.Column('email_enabled', sa.Boolean(), nullable=False),
    sa.Column('email_to', sa.String(length=320), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('resumes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('original_filename', sa.String(length=300), nullable=False),
    sa.Column('file_hash', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('job_titles', sa.JSON(), nullable=False),
    sa.Column('education', sa.JSON(), nullable=False),
    sa.Column('certifications', sa.JSON(), nullable=False),
    sa.Column('experience_years', sa.Float(), nullable=True),
    sa.Column('profile_text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_resumes_file_hash'), 'resumes', ['file_hash'], unique=False)
    op.create_table('search_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('companies_searched', sa.Integer(), nullable=False),
    sa.Column('jobs_fetched', sa.Integer(), nullable=False),
    sa.Column('new_jobs', sa.Integer(), nullable=False),
    sa.Column('qualified_jobs', sa.Integer(), nullable=False),
    sa.Column('errors', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('search_keywords',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('keyword', sa.String(length=120), nullable=False),
    sa.Column('aliases', sa.JSON(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('keyword')
    )
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=30), nullable=False),
    sa.Column('external_id', sa.String(length=200), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=True),
    sa.Column('company_name', sa.String(length=200), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('location', sa.String(length=500), nullable=True),
    sa.Column('employment_type', sa.String(length=100), nullable=True),
    sa.Column('workplace_type', sa.String(length=30), nullable=True),
    sa.Column('experience_text', sa.String(length=200), nullable=True),
    sa.Column('min_experience_years', sa.Float(), nullable=True),
    sa.Column('max_experience_years', sa.Float(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('application_url', sa.String(length=1000), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('expired_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'external_id', name='uq_job_source_external')
    )
    op.create_index('ix_jobs_active_company', 'jobs', ['is_active', 'company_id'], unique=False)
    op.create_index(op.f('ix_jobs_company_id'), 'jobs', ['company_id'], unique=False)
    op.create_index('ix_jobs_first_seen', 'jobs', ['first_seen_at'], unique=False)
    op.create_table('resume_skills',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('resume_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('resume_id', 'name', name='uq_resume_skill')
    )
    op.create_table('application_tracking',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('applied_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    op.create_index(op.f('ix_application_tracking_status'), 'application_tracking', ['status'], unique=False)
    op.create_table('job_matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('resume_id', sa.Integer(), nullable=True),
    sa.Column('keyword_qualified', sa.Boolean(), nullable=False),
    sa.Column('matched_keywords', sa.JSON(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('score_breakdown', sa.JSON(), nullable=False),
    sa.Column('matched_skills', sa.JSON(), nullable=False),
    sa.Column('missing_skills', sa.JSON(), nullable=False),
    sa.Column('excerpts', sa.JSON(), nullable=False),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('above_threshold', sa.Boolean(), nullable=False),
    sa.Column('scored_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    op.create_index('ix_job_matches_qualified_score', 'job_matches', ['keyword_qualified', 'score'], unique=False)
    op.create_table('notification_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'channel', name='uq_notification_job_channel')
    )
    op.create_table('saved_jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.Integer(), nullable=False),
    sa.Column('saved_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id')
    )
    # Supabase exposes every table in the "public" schema through its auto-generated
    # REST API, protected only by Row Level Security. JobRadar talks to Postgres
    # directly (as the table owner, which bypasses RLS), so we enable RLS with NO
    # policies: anyone using the public anon/authenticated API keys gets nothing.
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES + ["alembic_version"]:
            op.execute(f'ALTER TABLE IF EXISTS "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('saved_jobs')
    op.drop_table('notification_history')
    op.drop_index('ix_job_matches_qualified_score', table_name='job_matches')
    op.drop_table('job_matches')
    op.drop_index(op.f('ix_application_tracking_status'), table_name='application_tracking')
    op.drop_table('application_tracking')
    op.drop_table('resume_skills')
    op.drop_index('ix_jobs_first_seen', table_name='jobs')
    op.drop_index(op.f('ix_jobs_company_id'), table_name='jobs')
    op.drop_index('ix_jobs_active_company', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('search_keywords')
    op.drop_table('search_history')
    op.drop_index(op.f('ix_resumes_file_hash'), table_name='resumes')
    op.drop_table('resumes')
    op.drop_table('job_preferences')
    op.drop_table('embedding_cache')
    op.drop_table('companies')
