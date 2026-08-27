const API_BASE = '/api';

const state = {
    currentView: 'today',
    jobs: [],
    stats: {},
    briefing: null,
    currentPage: 1,
    totalPages: 1,
    filters: {
        source: '',
        location: '',
        status: '',
        dateFilter: '',
        search: '',
        sortBy: 'final_score',
        targetStatesOnly: false,
        realisticOnly: true,
        sponsorshipStatus: '',
        roleTier: '',
        minMatch: '',
        applyVerified: false,
    }
};

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModals();
    initFilters();
    initScraper();
    initProfile();
    initToday();
    initApplications();
    initCompanies();
    loadToday();
});

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.querySelector('.sidebar');
    
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            switchView(view);
            
            navItems.forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            
            if (window.innerWidth < 992) {
                sidebar.classList.remove('open');
            }
        });
    });
    
    menuToggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
    
    document.querySelectorAll('.view-all').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const view = link.dataset.view;
            switchView(view);
            document.querySelector(`.nav-item[data-view="${view}"]`).click();
        });
    });
    
    document.getElementById('refreshJobs').addEventListener('click', () => {
        loadCurrentView();
    });
    
    document.getElementById('globalSearch').addEventListener('input', debounce((e) => {
        state.filters.search = (e.target.value || '').trim();
        if (state.currentView === 'jobs') {
            loadJobs();
        }
    }, 300));
}

function switchView(view) {
    state.currentView = view;
    
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(`${view}View`).classList.add('active');
    
    document.getElementById('pageTitle').textContent = getViewTitle(view);
    
    loadCurrentView();
}

function getViewTitle(view) {
    const titles = {
        today: 'Today',
        dashboard: 'Overview',
        jobs: 'All Jobs',
        favorites: 'Favorites',
        applications: 'Applications',
        companies: 'Companies',
        insights: 'Insights',
        applied: 'Application Tracker',
        scraper: 'Job Search',
        profile: 'Profile'
    };
    return titles[view] || 'Today';
}

function loadCurrentView() {
    switch (state.currentView) {
        case 'today':
            loadToday();
            break;
        case 'dashboard':
            loadDashboard();
            break;
        case 'jobs':
            loadJobs();
            break;
        case 'favorites':
            loadFavorites();
            break;
        case 'applications':
            loadApplications();
            break;
        case 'companies':
            loadCompanies();
            break;
        case 'insights':
            loadInsights();
            break;
        case 'applied':
            loadApplied();
            break;
        case 'profile':
            loadProfile();
            break;
    }
}

// =============================================================================
// Today — the morning briefing
// =============================================================================

function initToday() {
    const limitSelect = document.getElementById('todayLimit');
    const realisticToggle = document.getElementById('todayRealisticOnly');
    const runNow = document.getElementById('runSearchNowBtn');
    const verifyTop = document.getElementById('verifyTopBtn');

    if (limitSelect) limitSelect.addEventListener('change', loadToday);
    if (realisticToggle) realisticToggle.addEventListener('change', loadToday);

    if (runNow) {
        runNow.addEventListener('click', async () => {
            runNow.disabled = true;
            runNow.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Searching…</span>';
            try {
                await startScrapeRun();
                pollScrapeUntilDone(() => {
                    runNow.disabled = false;
                    runNow.innerHTML = '<i class="fas fa-bolt"></i><span>Run search now</span>';
                    loadToday();
                });
            } catch (err) {
                showToast(err.message || 'Could not start the search', 'error');
                runNow.disabled = false;
                runNow.innerHTML = '<i class="fas fa-bolt"></i><span>Run search now</span>';
            }
        });
    }

    if (verifyTop) {
        verifyTop.addEventListener('click', async () => {
            verifyTop.disabled = true;
            verifyTop.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Checking…</span>';
            try {
                const res = await fetchAPI('/jobs/verify-top', {
                    method: 'POST',
                    body: JSON.stringify({ limit: 15 }),
                });
                const dead = res.dead || 0;
                const verified = res.verified || 0;
                showToast(
                    dead
                        ? `${dead} link(s) dead; ${verified} verified`
                        : `${verified} apply link(s) verified`,
                    dead ? 'error' : 'success',
                );
                loadToday();
            } catch (err) {
                showToast(err.message || 'Verification failed', 'error');
            }
            verifyTop.disabled = false;
            verifyTop.innerHTML = '<i class="fas fa-link"></i><span>Verify links</span>';
        });
    }
}

async function loadToday() {
    const limit = document.getElementById('todayLimit')?.value || 10;
    const realistic = document.getElementById('todayRealisticOnly')?.checked !== false;
    try {
        const data = await fetchAPI(`/briefing?limit=${limit}&realistic=${realistic}`);
        state.briefing = data;
        renderBriefing(data);
        renderSmartJobList('todayJobsList', data.top_jobs);
        loadAttention();
        updateNavBadges(data.counts);
    } catch (err) {
        document.getElementById('todayJobsList').innerHTML =
            `<div class="empty-state"><i class="fas fa-exclamation-triangle"></i>
             <p>Could not load your briefing: ${escapeHtml(err.message || 'unknown error')}</p></div>`;
    }
}

function renderBriefing(data) {
    const hour = new Date().getHours();
    const partOfDay = hour < 12 ? 'morning' : hour < 18 ? 'afternoon' : 'evening';
    const name = data.greeting_name ? `, ${data.greeting_name}` : '';
    document.getElementById('briefingGreeting').textContent =
        `Good ${partOfDay}${name}`;

    const c = data.counts;
    document.getElementById('briefingSub').textContent =
        c.applyable_total === 0
            ? 'No open jobs match your profile yet — run a search to populate your queue.'
            : `${c.applyable_total} open jobs match your profile. Here are the ${
                (data.top_jobs || []).length} you should look at first.`;

    const tiles = [
        { label: 'New today', value: c.new_today, icon: 'fa-clock', tone: 'blue' },
        { label: `Strong (${data.thresholds.strong}%+)`, value: c.strong_matches, icon: 'fa-bullseye', tone: 'green' },
        { label: `Excellent (${data.thresholds.excellent}%+)`, value: c.excellent_matches, icon: 'fa-star', tone: 'gold' },
        { label: 'Target companies', value: c.target_company_matches, icon: 'fa-building', tone: 'purple' },
        { label: 'Sponsorship-positive', value: c.sponsorship_positive, icon: 'fa-passport', tone: 'teal' },
        { label: 'Posted < 24h', value: c.posted_last_24h, icon: 'fa-fire', tone: 'red' },
        { label: 'Follow-ups due', value: c.followups_due, icon: 'fa-bell', tone: c.followups_due ? 'warn' : 'grey' },
    ];

    document.getElementById('briefingStrip').innerHTML = tiles.map(t => `
        <div class="briefing-tile ${t.tone}">
            <i class="fas ${t.icon}"></i>
            <span class="tile-value">${t.value}</span>
            <span class="tile-label">${t.label}</span>
        </div>
    `).join('');

    const run = data.last_run;
    const bar = document.getElementById('briefingRunBar');
    if (!run) {
        bar.innerHTML = `<span class="muted-note">No search has been recorded yet.</span>`;
    } else {
        const when = run.completed_at || run.started_at;
        const errors = run.error_count
            ? `<span class="pill pill-warn">${run.error_count} source error(s)</span>` : '';
        bar.innerHTML = `
            <span class="muted-note">Last search ${formatDate(when)} (${run.trigger}) —
                ${run.jobs_discovered} discovered, ${run.jobs_accepted} kept,
                ${run.duplicates} duplicates${run.avg_match !== null ? `, avg match ${run.avg_match}%` : ''}</span>
            ${errors}`;
    }
}

async function loadAttention() {
    try {
        const data = await fetchAPI('/notifications?unread=true');
        const items = data.notifications.slice(0, 8);
        const list = document.getElementById('attentionList');
        if (!items.length) {
            list.innerHTML = `<div class="empty-state small"><i class="fas fa-check-circle"></i>
                <p>Nothing needs your attention right now.</p></div>`;
            return;
        }
        list.innerHTML = items.map(n => `
            <div class="attention-item ${n.severity}" ${n.job_id ? `data-job-id="${n.job_id}"` : ''}>
                <i class="fas ${notificationIcon(n.kind)}"></i>
                <div class="attention-text">
                    <strong>${escapeHtml(n.title)}</strong>
                    <span>${escapeHtml(n.body || '')}</span>
                </div>
                <span class="attention-time">${formatDate(n.created_at)}</span>
            </div>
        `).join('');
        list.querySelectorAll('.attention-item[data-job-id]').forEach(el => {
            el.addEventListener('click', () => openJobModal(parseInt(el.dataset.jobId, 10)));
        });
    } catch (err) {
        document.getElementById('attentionList').innerHTML = '';
    }
}

function notificationIcon(kind) {
    return {
        high_match: 'fa-bullseye',
        target_company: 'fa-building',
        sponsorship_positive: 'fa-passport',
        followup_due: 'fa-bell',
        saved_job_expiring: 'fa-hourglass-half',
        fresh_job: 'fa-fire',
    }[kind] || 'fa-info-circle';
}

function updateNavBadges(counts) {
    const todayBadge = document.getElementById('todayBadge');
    if (todayBadge) {
        todayBadge.textContent = counts.strong_matches || '';
        todayBadge.style.display = counts.strong_matches ? 'inline-flex' : 'none';
    }
    const followupBadge = document.getElementById('followupBadge');
    if (followupBadge) {
        followupBadge.textContent = counts.followups_due || '';
        followupBadge.style.display = counts.followups_due ? 'inline-flex' : 'none';
    }
}

// =============================================================================
// Smart job card
// =============================================================================

const SPONSORSHIP_UI = {
    green: { icon: '🟢', label: 'Sponsorship looks possible' },
    yellow: { icon: '🟡', label: 'Sponsorship unclear' },
    red: { icon: '🔴', label: 'Likely blocked' },
    unknown: { icon: '⚪', label: 'Sponsorship unknown' },
};

const FRESHNESS_UI = {
    hot: { icon: '🔥', label: '< 24 hours' },
    fresh: { icon: '🟢', label: '1-3 days' },
    recent: { icon: '🟡', label: '4-7 days' },
    aging: { icon: '⚪', label: '8-14 days' },
    stale: { icon: '🔴', label: '> 14 days' },
    unknown: { icon: '❔', label: 'Date unknown' },
};

function renderSmartJobList(containerId, jobs) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!jobs || !jobs.length) {
        container.innerHTML = `<div class="empty-state">
            <i class="fas fa-inbox"></i>
            <p>Nothing to apply to right now. Run a search to refresh your queue.</p>
        </div>`;
        return;
    }
    container.innerHTML = jobs.map((job, index) => smartJobCard(job, index + 1)).join('');
    wireSmartJobCards(container);
}

function smartJobCard(job, rank) {
    const sponsorship = SPONSORSHIP_UI[job.sponsorship_status] || SPONSORSHIP_UI.unknown;
    const freshness = FRESHNESS_UI[job.freshness_bucket] || FRESHNESS_UI.unknown;
    const reasons = (job.match_reasons || []).slice(0, 6);
    const gaps = (job.match_gaps || []).slice(0, 4);
    const risks = (job.match_risks || []).slice(0, 3);
    const tier = job.role_tier ? `Tier ${job.role_tier}` : 'Unclassified role';

    const applyButton = job.can_apply
        ? `<a class="btn btn-primary btn-sm" href="${escapeAttr(job.application_url)}"
              target="_blank" rel="noopener" data-apply-job="${job.id}">
             <i class="fas fa-external-link-alt"></i> Apply now</a>`
        : `<button class="btn btn-sm" disabled title="${escapeAttr(job.can_apply_label || 'Unable to verify')}">
             <i class="fas fa-unlink"></i> ${escapeHtml(job.can_apply_label || (job.application_url ? 'Unable to verify' : 'No apply link'))}</button>`;

    return `
    <article class="smart-card" data-job-id="${job.id}">
        <div class="smart-rank">#${rank}</div>
        <div class="smart-main">
            <div class="smart-head">
                <h4 class="smart-title" data-open-job="${job.id}">${escapeHtml(job.title)}</h4>
                <div class="smart-scores">
                    <span class="score-chip ${matchClass(job.candidate_match_score)}"
                          title="Candidate match">${job.candidate_match_score ?? '—'}%</span>
                    <span class="score-chip subtle" title="Opportunity score">Opp ${job.opportunity_score ?? '—'}</span>
                    <span class="score-chip subtle" title="Listing quality">Q ${job.job_quality_score ?? '—'}</span>
                </div>
            </div>
            <div class="smart-meta">
                <span><i class="fas fa-building"></i> ${escapeHtml(job.company)}</span>
                <span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location || 'Location unknown')}</span>
                <span><i class="fas fa-laptop-house"></i> ${escapeHtml(job.remote_type || 'unknown')}</span>
                <span title="${escapeAttr(job.sponsorship_reason || sponsorship.label)}">${sponsorship.icon} ${sponsorship.label}</span>
                <span title="${escapeAttr(freshness.label)}">${freshness.icon} ${freshness.label}</span>
                <span class="badge-source">${escapeHtml(job.source || 'unknown')}</span>
                <span class="badge-tier">${tier}</span>
                <span><i class="fas fa-dollar-sign"></i> ${escapeHtml(job.salary_display || 'Unknown')}</span>
            </div>
            <div class="smart-explain">
                ${reasons.length ? `<div class="explain-block ok">
                    <span class="explain-label">Why apply</span>
                    <ul>${reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul></div>` : ''}
                ${gaps.length ? `<div class="explain-block warn">
                    <span class="explain-label">Gaps</span>
                    <ul>${gaps.map(g => `<li>${escapeHtml(g)}</li>`).join('')}</ul></div>` : ''}
                ${risks.length ? `<div class="explain-block risk">
                    <span class="explain-label">Risks</span>
                    <ul>${risks.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul></div>` : ''}
            </div>
            <div class="smart-actions">
                <button class="btn btn-sm btn-ghost" data-open-job="${job.id}">
                    <i class="fas fa-eye"></i> View</button>
                <button class="btn btn-sm btn-ghost" data-prepare-job="${job.id}">
                    <i class="fas fa-wand-magic-sparkles"></i> Prepare</button>
                ${applyButton}
                <button class="btn btn-sm btn-ghost" data-mark-applied="${job.id}">
                    <i class="fas fa-check"></i> Mark applied</button>
                <button class="btn btn-sm btn-ghost" data-favorite-job="${job.id}">
                    <i class="${job.is_favorite ? 'fas' : 'far'} fa-star"></i></button>
                <button class="btn btn-sm btn-ghost" data-not-interested="${job.id}"
                        title="Not interested">
                    <i class="fas fa-ban"></i></button>
            </div>
        </div>
    </article>`;
}

function wireSmartJobCards(container) {
    container.querySelectorAll('[data-open-job]').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            openJobModal(parseInt(el.dataset.openJob, 10));
        });
    });
    container.querySelectorAll('[data-prepare-job]').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            openPrepModal(parseInt(el.dataset.prepareJob, 10));
        });
    });
    container.querySelectorAll('[data-mark-applied]').forEach(el => {
        el.addEventListener('click', async (e) => {
            e.stopPropagation();
            await markApplied(parseInt(el.dataset.markApplied, 10));
        });
    });
    container.querySelectorAll('[data-favorite-job]').forEach(el => {
        el.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = parseInt(el.dataset.favoriteJob, 10);
            const icon = el.querySelector('i');
            const nowFavorite = icon.classList.contains('far');
            await fetchAPI(`/jobs/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ is_favorite: nowFavorite }),
            });
            icon.classList.toggle('far');
            icon.classList.toggle('fas');
        });
    });
    container.querySelectorAll('[data-not-interested]').forEach(el => {
        el.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = parseInt(el.dataset.notInterested, 10);
            await fetchAPI(`/jobs/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ is_not_interested: true }),
            });
            const card = el.closest('.smart-card');
            if (card) card.remove();
            showToast('Marked as not interested', 'success');
        });
    });
}

function matchClass(score) {
    if (score === null || score === undefined) return 'unknown';
    if (score >= 90) return 'excellent';
    if (score >= 75) return 'strong';
    if (score >= 60) return 'fair';
    return 'weak';
}

async function markApplied(jobId) {
    try {
        await fetchAPI('/applications', {
            method: 'POST',
            body: JSON.stringify({ job_id: jobId, status: 'APPLIED' }),
        });
        showToast('Marked as applied — follow-up scheduled', 'success');
        loadToday();
    } catch (err) {
        showToast(err.message || 'Could not record the application', 'error');
    }
}

// =============================================================================
// Application preparation
// =============================================================================

async function openPrepModal(jobId) {
    const modal = document.getElementById('prepModal');
    const body = document.getElementById('prepBody');
    modal.classList.add('active');
    body.innerHTML = `<div class="loading"><i class="fas fa-spinner fa-spin"></i> Preparing…</div>`;

    try {
        const prep = await fetchAPI(`/jobs/${jobId}/prepare`, { method: 'POST' });
        const job = await fetchAPI(`/jobs/${jobId}`);
        document.getElementById('prepTitle').textContent =
            `Prepare: ${job.title} @ ${job.company}`;

        const sensitive = prep.screening_questions.filter(q => q.sensitive);
        const answerable = prep.screening_questions.filter(q => !q.sensitive);

        body.innerHTML = `
        <div class="prep-warning">
            <i class="fas fa-triangle-exclamation"></i>
            ${escapeHtml(prep.disclaimer)}
        </div>

        <div class="prep-grid">
            <section class="prep-block">
                <h4>Match breakdown — ${prep.match_score}%</h4>
                ${breakdownBars(prep.breakdown)}
            </section>

            <section class="prep-block">
                <h4>Work authorization</h4>
                <p><strong>${(SPONSORSHIP_UI[prep.sponsorship.status] || SPONSORSHIP_UI.unknown).icon}
                   ${escapeHtml(prep.sponsorship.reason || 'Unknown')}</strong></p>
                ${prep.sponsorship.evidence
                    ? `<blockquote class="evidence">${escapeHtml(prep.sponsorship.evidence)}</blockquote>`
                    : `<p class="muted-note">No statement found in the posting.</p>`}
            </section>
        </div>

        <section class="prep-block">
            <h4>Resume recommendation</h4>
            <p>${escapeHtml(prep.resume_recommendation)}</p>
            <ul class="prep-list">
                ${prep.resume_bullets.map(b => `<li>
                    <strong>${escapeHtml(b.source)}</strong> — ${escapeHtml(b.why)}<br>
                    <span class="muted-note">${escapeHtml(b.action)}</span></li>`).join('')}
            </ul>
        </section>

        <section class="prep-block">
            <h4>Professional summary <button class="btn btn-xs" data-copy="summary">Copy</button></h4>
            <textarea class="prep-text" id="prepSummary" rows="4">${escapeHtml(prep.professional_summary)}</textarea>
        </section>

        <section class="prep-block">
            <h4>Cover letter draft <button class="btn btn-xs" data-copy="cover">Copy</button></h4>
            <textarea class="prep-text" id="prepCover" rows="14">${escapeHtml(prep.cover_letter)}</textarea>
        </section>

        <section class="prep-block">
            <h4>Likely questions — suggested drafts</h4>
            ${answerable.map(q => `<div class="prep-qa">
                <strong>${escapeHtml(q.question)}</strong>
                <p>${escapeHtml(q.suggested_answer)}</p>
                <span class="muted-note">${escapeHtml(q.note || '')}</span>
            </div>`).join('')}
        </section>

        <section class="prep-block danger">
            <h4><i class="fas fa-user-shield"></i> You must answer these yourself</h4>
            <p class="muted-note">Authorization, citizenship, demographic and legal
               questions are never pre-filled.</p>
            ${sensitive.map(q => `<div class="prep-qa sensitive">
                <strong>${escapeHtml(q.question)}</strong>
                <span class="pill pill-warn">${escapeHtml(q.category)}</span>
            </div>`).join('')}
        </section>

        <div class="prep-footer">
            ${job.can_apply
                ? `<a class="btn btn-primary" target="_blank" rel="noopener"
                      href="${escapeAttr(job.application_url)}">
                     <i class="fas fa-external-link-alt"></i> Open official application</a>`
                : `<button class="btn" disabled>No verified application URL</button>`}
            <button class="btn btn-ghost" data-mark-applied-modal="${jobId}">
                <i class="fas fa-check"></i> I submitted this — mark applied</button>
        </div>`;

        body.querySelector('[data-copy="summary"]')?.addEventListener('click', () =>
            copyText(document.getElementById('prepSummary').value));
        body.querySelector('[data-copy="cover"]')?.addEventListener('click', () =>
            copyText(document.getElementById('prepCover').value));
        body.querySelector(`[data-mark-applied-modal="${jobId}"]`)
            ?.addEventListener('click', async () => {
                await markApplied(jobId);
                modal.classList.remove('active');
            });
    } catch (err) {
        body.innerHTML = `<div class="empty-state"><i class="fas fa-exclamation-triangle"></i>
            <p>${escapeHtml(err.message || 'Could not prepare this application')}</p></div>`;
    }
}

function breakdownBars(breakdown) {
    const labels = {
        skills: 'Technical skills', responsibilities: 'Responsibilities',
        experience: 'Experience', education: 'Education', role: 'Role alignment',
        location: 'Location', authorization: 'Work authorization',
    };
    return `<div class="breakdown">${Object.entries(breakdown).map(([key, value]) => `
        <div class="breakdown-row">
            <span class="breakdown-label">${labels[key] || key}</span>
            <div class="breakdown-bar"><div class="breakdown-fill ${matchClass(value)}"
                 style="width:${Math.max(2, Math.min(100, value))}%"></div></div>
            <span class="breakdown-value">${value}</span>
        </div>`).join('')}</div>`;
}

async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
    } catch (err) {
        showToast('Could not copy automatically — select and copy manually', 'error');
    }
}

// =============================================================================
// Applications view
// =============================================================================

function initApplications() {
    const filter = document.getElementById('applicationStatusFilter');
    if (filter) filter.addEventListener('change', loadApplications);
}

async function loadApplications() {
    try {
        const [apps, followups] = await Promise.all([
            fetchAPI('/applications'),
            fetchAPI('/followups'),
        ]);

        const filter = document.getElementById('applicationStatusFilter');
        if (filter && filter.options.length <= 1) {
            apps.statuses.forEach(s => {
                const option = document.createElement('option');
                option.value = s;
                option.textContent = s.replace(/_/g, ' ');
                filter.appendChild(option);
            });
        }
        const selected = filter ? filter.value : '';

        const dueList = document.getElementById('followupList');
        dueList.innerHTML = followups.due.length
            ? followups.due.map(a => `
                <div class="followup-item">
                    <div>
                        <strong>${escapeHtml(a.company || '')}</strong> — ${escapeHtml(a.role || '')}
                        <span class="muted-note">due ${formatDate(a.next_followup_date)}</span>
                    </div>
                    <button class="btn btn-sm btn-primary" data-followup="${a.id}">
                        <i class="fas fa-check"></i> Logged follow-up</button>
                </div>`).join('')
            : `<div class="empty-state small"><i class="fas fa-check-circle"></i>
                 <p>No follow-ups are due.</p></div>`;

        dueList.querySelectorAll('[data-followup]').forEach(btn => {
            btn.addEventListener('click', async () => {
                await fetchAPI(`/applications/${btn.dataset.followup}/followup`,
                               { method: 'POST', body: JSON.stringify({}) });
                showToast('Follow-up recorded', 'success');
                loadApplications();
            });
        });

        const rows = apps.applications.filter(a => !selected || a.status === selected);
        document.getElementById('applicationsTableBody').innerHTML = rows.length
            ? rows.map(a => `
                <tr>
                    <td>${escapeHtml(a.company || '')}</td>
                    <td>${escapeHtml(a.role || '')}</td>
                    <td>
                        <select class="status-select" data-app-status="${a.id}">
                            ${apps.statuses.map(s =>
                                `<option value="${s}" ${s === a.status ? 'selected' : ''}>
                                   ${s.replace(/_/g, ' ')}</option>`).join('')}
                        </select>
                    </td>
                    <td>${a.date_applied ? formatDate(a.date_applied) : '—'}</td>
                    <td>${a.next_followup_date ? formatDate(a.next_followup_date) : '—'}</td>
                    <td>${a.application_url
                        ? `<a href="${escapeAttr(a.application_url)}" target="_blank" rel="noopener">
                             <i class="fas fa-external-link-alt"></i></a>` : ''}</td>
                </tr>`).join('')
            : `<tr><td colspan="6" class="muted-note">
                 No applications recorded yet. Mark a job as applied from Today.</td></tr>`;

        document.querySelectorAll('[data-app-status]').forEach(select => {
            select.addEventListener('change', async () => {
                await fetchAPI(`/applications/${select.dataset.appStatus}`, {
                    method: 'PUT',
                    body: JSON.stringify({ status: select.value }),
                });
                showToast('Status updated', 'success');
                loadApplications();
            });
        });
    } catch (err) {
        showToast(err.message || 'Could not load applications', 'error');
    }
}

// =============================================================================
// Companies view
// =============================================================================

function initCompanies() {
    const button = document.getElementById('addWatchlistBtn');
    if (!button) return;
    button.addEventListener('click', async () => {
        const input = document.getElementById('newWatchlistCompany');
        const name = (input.value || '').trim();
        if (!name) return;
        await fetchAPI('/watchlist', {
            method: 'POST',
            body: JSON.stringify({ name, priority: 1 }),
        });
        input.value = '';
        loadCompanies();
    });
}

async function loadCompanies() {
    try {
        const data = await fetchAPI('/watchlist');
        document.getElementById('companyGrid').innerHTML = data.companies.map(c => {
            const statuses = c.sponsorship_signals.posting_statuses || {};
            const chips = Object.entries(statuses).map(([status, count]) =>
                `<span class="pill pill-${status}">${(SPONSORSHIP_UI[status] || SPONSORSHIP_UI.unknown).icon} ${count}</span>`
            ).join('');
            return `
            <div class="company-card">
                <div class="company-head">
                    <h4>${escapeHtml(c.name)}</h4>
                    <button class="btn btn-xs btn-ghost" data-remove-company="${c.id}"
                            title="Remove from watchlist"><i class="fas fa-times"></i></button>
                </div>
                <div class="company-stats">
                    <span><strong>${c.jobs_found}</strong> jobs found</span>
                    <span><strong>${c.matching_jobs}</strong> strong matches</span>
                    <span><strong>${c.avg_match ?? '—'}</strong> avg match</span>
                    <span><strong>${c.applications}</strong> applications</span>
                    <span><strong>${c.interviews}</strong> interviews</span>
                    <span><strong>${c.offers}</strong> offers</span>
                </div>
                <div class="company-sponsorship">
                    ${chips || '<span class="muted-note">No postings scored yet</span>'}
                    ${c.sponsorship_signals.e_verify_listed
                        ? '<span class="pill pill-green">E-Verify listed</span>' : ''}
                </div>
                <p class="muted-note">${escapeHtml(c.sponsorship_signals.note)}</p>
            </div>`;
        }).join('');

        document.querySelectorAll('[data-remove-company]').forEach(btn => {
            btn.addEventListener('click', async () => {
                await fetchAPI(`/watchlist/${btn.dataset.removeCompany}`, { method: 'DELETE' });
                loadCompanies();
            });
        });
    } catch (err) {
        showToast(err.message || 'Could not load companies', 'error');
    }
}

// =============================================================================
// Insights view
// =============================================================================

async function loadInsights() {
    try {
        const [analytics, metrics, runs, external] = await Promise.all([
            fetchAPI('/analytics/outcomes'),
            fetchAPI('/sources/metrics'),
            fetchAPI('/search-runs?limit=15'),
            fetchAPI('/external-search'),
        ]);

        renderAnalytics(analytics);

        document.getElementById('sourceMetricsBody').innerHTML = metrics.sources.length
            ? metrics.sources.map(s => `
                <tr>
                    <td>${escapeHtml(s.source)}</td>
                    <td>${s.jobs_discovered}</td>
                    <td>${s.jobs_accepted}</td>
                    <td>${s.duplicates}</td>
                    <td>${s.expired}</td>
                    <td>${s.missing_apply_url}</td>
                    <td>${s.avg_match ?? '—'}</td>
                    <td>${s.failures ? `<span class="pill pill-warn">${s.failures}</span>` : '0'}</td>
                    <td>${s.last_successful_run ? formatDate(s.last_successful_run) : 'never'}</td>
                </tr>`).join('')
            : `<tr><td colspan="9" class="muted-note">No source runs recorded yet.</td></tr>`;

        document.getElementById('searchRunsBody').innerHTML = runs.runs.length
            ? runs.runs.map(r => `
                <tr>
                    <td>${formatDate(r.started_at)}</td>
                    <td>${escapeHtml(r.trigger)}</td>
                    <td>${escapeHtml(r.status)}</td>
                    <td>${r.jobs_discovered}</td>
                    <td>${r.jobs_accepted}</td>
                    <td>${r.duplicates}</td>
                    <td>${r.avg_match ?? '—'}</td>
                    <td>${r.error_count || 0}</td>
                </tr>`).join('')
            : `<tr><td colspan="8" class="muted-note">No searches recorded yet.</td></tr>`;

        document.getElementById('externalLinks').innerHTML = external.links.map(l => `
            <a class="quick-link" href="${escapeAttr(l.url)}" target="_blank" rel="noopener">
                <i class="fas fa-external-link-alt"></i> ${escapeHtml(l.name)}
                <span class="pill">External Search</span>
            </a>`).join('');
    } catch (err) {
        showToast(err.message || 'Could not load insights', 'error');
    }
}

function renderAnalytics(a) {
    const panel = document.getElementById('analyticsPanel');
    if (!a.total_applications) {
        panel.innerHTML = `<div class="empty-state"><i class="fas fa-seedling"></i>
            <p>${escapeHtml(a.message)}</p></div>`;
        return;
    }
    const table = (title, rows) => rows.length ? `
        <div class="analytics-block">
            <h4>${title}</h4>
            <table class="application-table">
                <thead><tr><th></th><th>Apps</th><th>Interviews</th><th>Rate</th></tr></thead>
                <tbody>${rows.map(r => `<tr>
                    <td>${escapeHtml(String(r.key))}</td>
                    <td>${r.applications}</td>
                    <td>${r.interviews}</td>
                    <td>${r.interview_rate ?? '—'}%${r.confident ? '' :
                        ' <span class="muted-note">(small sample)</span>'}</td>
                </tr>`).join('')}</tbody>
            </table>
        </div>` : '';

    panel.innerHTML = `
        <div class="analytics-summary">
            <span><strong>${a.total_applications}</strong> applications</span>
            <span><strong>${a.interviews}</strong> interviews</span>
            <span><strong>${a.offers}</strong> offers</span>
            <span><strong>${a.overall_interview_rate ?? '—'}%</strong> interview rate</span>
        </div>
        ${table('By role', a.by_role_family)}
        ${table('By match band', a.by_score_band)}
        ${table('By company', a.by_company.slice(0, 10))}
        ${table('By source', a.by_source)}
        <div class="analytics-block">
            <h4>Most requested skills in your queue</h4>
            <div class="skill-demand">${a.skill_demand.map(s =>
                `<span class="pill">${escapeHtml(s.skill)} <strong>${s.share}%</strong></span>`
            ).join('')}</div>
        </div>
        <div class="analytics-block">
            <h4>Recommendations</h4>
            <ul class="prep-list">${a.recommendations.map(r =>
                `<li>${escapeHtml(r.text)}</li>`).join('')}</ul>
        </div>`;
}

async function loadDashboard() {
    try {
        const stats = await fetchAPI('/stats');
        state.stats = stats;
        
        document.getElementById('totalJobs').textContent = stats.total_jobs || 0;
        document.getElementById('newToday').textContent = stats.new_today || 0;
        document.getElementById('favoriteJobs').textContent = stats.favorite_jobs || 0;
        document.getElementById('appliedJobs').textContent = `${stats.applied_jobs || 0} (${stats.response_rate || 0}%)`;
        
        renderSourceChart(stats.by_source || {});
        renderStatusChart(stats.by_status || {});
        
        const jobs = await fetchAPI('/jobs?per_page=5');
        renderJobList('recentJobs', jobs.jobs || []);
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

function renderSourceChart(data) {
    const container = document.getElementById('sourceChart');
    const colors = {
        linkedin: '#0077b5',
        remoteok: '#ff5733',
        themuse: '#009688',
        remotive: '#8b5cf6',
        arbeitnow: '#4caf50',
        manual: '#64748b'
    };
    
    const maxValue = Math.max(...Object.values(data), 1);
    
    container.innerHTML = Object.entries(data).map(([source, count]) => `
        <div class="source-bar">
            <span class="label">${capitalizeFirst(source)}</span>
            <div class="bar-container">
                <div class="bar" style="width: ${(count / maxValue) * 100}%; background: ${colors[source] || '#64748b'}"></div>
            </div>
            <span class="count">${count}</span>
        </div>
    `).join('') || '<p class="empty-state">No data yet</p>';
}

function renderStatusChart(data) {
    const container = document.getElementById('statusChart');
    const statusColors = {
        not_applied: '#64748b',
        applied: '#3b82f6',
        interviewing: '#f59e0b',
        offer: '#10b981',
        rejected: '#ef4444',
        withdrawn: '#94a3b8'
    };
    
    const statusLabels = {
        not_applied: 'Not Applied',
        applied: 'Applied',
        interviewing: 'Interviewing',
        offer: 'Offer',
        rejected: 'Rejected',
        withdrawn: 'Withdrawn'
    };
    
    container.innerHTML = Object.entries(data).map(([status, count]) => `
        <div class="status-item">
            <span class="status-dot" style="background: ${statusColors[status] || '#64748b'}"></span>
            <span class="label">${statusLabels[status] || status}</span>
            <span class="count">${count}</span>
        </div>
    `).join('') || '<p class="empty-state">No applications yet</p>';
}

async function loadJobs() {
    try {
        const params = new URLSearchParams({
            page: state.currentPage,
            per_page: 20,
            sort_by: state.filters.sortBy || 'final_score',
            ...(state.filters.source && { source: state.filters.source }),
            ...(state.filters.location && { location: state.filters.location }),
            ...(state.filters.status && { status: state.filters.status }),
            ...(state.filters.dateFilter && { date_filter: state.filters.dateFilter }),
            ...(state.filters.search && { search: state.filters.search }),
            ...(state.filters.targetStatesOnly && { target_states_only: 'true' }),
            ...(state.filters.realisticOnly && { realistic_only: 'true' }),
            ...(state.filters.sponsorshipStatus && { sponsorship_status: state.filters.sponsorshipStatus }),
            ...(state.filters.roleTier && { role_tier: state.filters.roleTier }),
            ...(state.filters.minMatch && { min_match: state.filters.minMatch }),
            ...(state.filters.applyVerified && { apply_url_verified: 'true' }),
        });
        
        const data = await fetchAPI(`/jobs?${params}`);
        state.jobs = data.jobs || [];
        state.totalPages = data.pages || 1;
        
        renderJobList('jobsList', state.jobs);
        renderPagination();
        loadMetroBreakdown();
    } catch (error) {
        console.error('Error loading jobs:', error);
    }
}

async function loadMetroBreakdown() {
    const el = document.getElementById('metroOpportunityPanel');
    if (!el) return;
    try {
        const data = await fetchAPI('/metros/opportunity?metros=Hartford,Dallas-Fort Worth,Boston');
        if (data.error) {
            el.innerHTML = `<p class="empty-state">${escapeHtml(data.error)}</p>`;
            return;
        }
        el.innerHTML = (data.metros || []).map(m => {
            if (m.error) return `<div class="metro-row"><strong>${escapeHtml(m.metro_name)}</strong>: ${escapeHtml(m.error)}</div>`;
            return `<div class="metro-row">
                <strong>${escapeHtml(m.metro_name || '')}</strong>
                <span class="metro-flag">${escapeHtml(m.flag || '')}</span>
                density ${m.sponsor_density ?? '—'} ·
                concentration ${m.concentration_penalty ?? '—'} ·
                <em>opportunity ${m.location_opportunity_score ?? '—'}</em>
                · filings ${m.de_filing_count ?? 0}
            </div>`;
        }).join('') + `<p class="metro-formula">${escapeHtml(data.formula || '')}</p>`;
    } catch (e) {
        el.innerHTML = '<p class="empty-state">Metro scores unavailable — load LCA data first</p>';
    }
}

async function loadFavorites() {
    try {
        const data = await fetchAPI('/jobs?is_favorite=true&per_page=100');
        renderJobList('favoritesList', data.jobs || []);
    } catch (error) {
        console.error('Error loading favorites:', error);
    }
}

async function loadApplied() {
    try {
        const applied = await fetchAPI('/jobs?status=applied&per_page=100');
        const interviewing = await fetchAPI('/jobs?status=interviewing&per_page=100');
        const offers = await fetchAPI('/jobs?status=offer&per_page=100');
        
        renderPipelineJobs('appliedList', applied.jobs || []);
        renderPipelineJobs('interviewingList', interviewing.jobs || []);
        renderPipelineJobs('offerList', offers.jobs || []);
    } catch (error) {
        console.error('Error loading applied jobs:', error);
    }
}

function renderJobList(containerId, jobs) {
    renderSmartJobList(containerId, jobs);
}

function getMatchLevel(score) {
    if (score >= 70) return 'excellent';
    if (score >= 50) return 'good';
    return 'moderate';
}

function renderPipelineJobs(containerId, jobs) {
    const container = document.getElementById(containerId);
    
    if (!jobs.length) {
        container.innerHTML = '<p class="empty-state" style="padding: 20px; font-size: 0.875rem;">No jobs</p>';
        return;
    }
    
    container.innerHTML = jobs.map(job => `
        <div class="pipeline-job" data-id="${job.id}">
            <div class="title">${escapeHtml(job.title)}</div>
            <div class="company">${escapeHtml(job.company)}</div>
        </div>
    `).join('');

    container.querySelectorAll('.pipeline-job').forEach(card => {
        card.addEventListener('click', () => {
            openJobModal(parseInt(card.dataset.id, 10));
        });
    });
}

function renderPagination() {
    const container = document.getElementById('pagination');
    
    if (state.totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = `
        <button onclick="changePage(${state.currentPage - 1})" ${state.currentPage === 1 ? 'disabled' : ''}>
            <i class="fas fa-chevron-left"></i>
        </button>
    `;
    
    for (let i = 1; i <= Math.min(state.totalPages, 5); i++) {
        html += `
            <button onclick="changePage(${i})" class="${state.currentPage === i ? 'active' : ''}">
                ${i}
            </button>
        `;
    }
    
    html += `
        <button onclick="changePage(${state.currentPage + 1})" ${state.currentPage === state.totalPages ? 'disabled' : ''}>
            <i class="fas fa-chevron-right"></i>
        </button>
    `;
    
    container.innerHTML = html;
}

function changePage(page) {
    if (page < 1 || page > state.totalPages) return;
    state.currentPage = page;
    loadJobs();
}

function initFilters() {
    const bind = (id, key, transform) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('change', (e) => {
            const value = transform ? transform(e.target) : e.target.value;
            state.filters[key] = value;
            state.currentPage = 1;
            loadJobs();
        });
    };

    bind('sourceFilter', 'source');
    bind('sortFilter', 'sortBy');
    bind('locationFilter', 'location');
    bind('dateFilter', 'dateFilter');
    bind('statusFilter', 'status');
    bind('sponsorshipFilter', 'sponsorshipStatus');
    bind('roleTierFilter', 'roleTier');
    bind('minMatchFilter', 'minMatch');
    bind('realisticOnlyFilter', 'realisticOnly', (el) => el.checked);
    bind('applyVerifiedFilter', 'applyVerified', (el) => el.checked);

    const sortEl = document.getElementById('sortFilter');
    if (sortEl && !sortEl.value) sortEl.value = 'final_score';

    document.getElementById('clearFilters').addEventListener('click', () => {
        state.filters = {
            source: '', location: '', status: '', dateFilter: '', search: '',
            sortBy: 'final_score', targetStatesOnly: false, realisticOnly: true,
            sponsorshipStatus: '', roleTier: '', minMatch: '', applyVerified: false,
        };
        state.currentPage = 1;
        ['sourceFilter', 'locationFilter', 'dateFilter', 'statusFilter',
         'sponsorshipFilter', 'roleTierFilter', 'minMatchFilter'].forEach((id) => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const sort = document.getElementById('sortFilter');
        if (sort) sort.value = 'final_score';
        const realistic = document.getElementById('realisticOnlyFilter');
        if (realistic) realistic.checked = true;
        const verified = document.getElementById('applyVerifiedFilter');
        if (verified) verified.checked = false;
        const search = document.getElementById('globalSearch');
        if (search) search.value = '';
        loadJobs();
    });
}

function initModals() {
    const jobModal = document.getElementById('jobModal');
    const addJobModal = document.getElementById('addJobModal');
    const prepModal = document.getElementById('prepModal');
    const closeAll = () => {
        [jobModal, addJobModal, prepModal].forEach(m => m && m.classList.remove('active'));
    };

    document.getElementById('closeModal').addEventListener('click', closeAll);
    document.getElementById('closeAddModal').addEventListener('click', closeAll);
    document.getElementById('closePrepModal')?.addEventListener('click', closeAll);

    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', closeAll);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAll();
        // Keyboard shortcuts: g then t/j/a jumps between views
        if (e.target.matches('input, textarea, select')) return;
        const shortcuts = { t: 'today', j: 'jobs', a: 'applications',
                            c: 'companies', i: 'insights', s: 'scraper' };
        if (e.key === '/' ) {
            e.preventDefault();
            document.getElementById('globalSearch')?.focus();
        } else if (shortcuts[e.key]) {
            document.querySelector(`.nav-item[data-view="${shortcuts[e.key]}"]`)?.click();
        }
    });
    
    document.getElementById('addJobBtn').addEventListener('click', () => {
        addJobModal.classList.add('active');
    });
    
    document.getElementById('addJobForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData);
        
        try {
            await fetchAPI('/jobs/add', {
                method: 'POST',
                body: JSON.stringify(data)
            });
            
            addJobModal.classList.remove('active');
            e.target.reset();
            loadCurrentView();
        } catch (error) {
            console.error('Error adding job:', error);
        }
    });
}

async function openJobModal(jobId) {
    try {
        const job = await fetchAPI(`/jobs/${jobId}`);
        
        document.getElementById('modalTitle').textContent = job.title;
        document.getElementById('modalBody').innerHTML = `
            <div class="job-detail">
                <div class="detail-header">
                    <div class="company-logo large">${getCompanyInitials(job.company)}</div>
                    <div>
                        <h3>${escapeHtml(job.company)}</h3>
                        <p><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location || 'Remote')}</p>
                    </div>
                    <span class="source-badge ${job.source}">${job.source}</span>
                </div>
                
                <div class="detail-info">
                    <div class="info-row">
                        <span class="label">Posted:</span>
                        <span>${job.date_posted ? formatDate(job.date_posted) : 'Unknown'}
                          <span class="muted-note">(${escapeHtml(job.date_posted_origin || 'unknown')})</span></span>
                    </div>
                    <div class="info-row">
                        <span class="label">Discovered:</span>
                        <span>${formatDate(job.discovered_at || job.date_scraped)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Freshness:</span>
                        <span>${(FRESHNESS_UI[job.freshness_bucket] || FRESHNESS_UI.unknown).icon}
                          ${(FRESHNESS_UI[job.freshness_bucket] || FRESHNESS_UI.unknown).label}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Salary:</span>
                        <span>${escapeHtml(job.salary_display || 'Unknown')}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Experience required:</span>
                        <span>${job.required_years !== null && job.required_years !== undefined
                            ? `${job.required_years} years` : 'Not stated'}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Apply link:</span>
                        <span>${escapeHtml(job.application_url_status || 'unknown')}
                          ${job.last_verified_at
                            ? `<span class="muted-note">checked ${formatDate(job.last_verified_at)}</span>` : ''}</span>
                    </div>
                </div>

                <div class="detail-scores">
                    <div class="score-summary">
                        <span class="score-chip ${matchClass(job.candidate_match_score)}">
                            Match ${job.candidate_match_score ?? '—'}%</span>
                        <span class="score-chip subtle">Opportunity ${job.opportunity_score ?? '—'}</span>
                        <span class="score-chip subtle">Quality ${job.job_quality_score ?? '—'}</span>
                        <span class="score-chip subtle">Final ${job.final_score ?? '—'}</span>
                    </div>
                    ${Object.keys(job.match_breakdown || {}).length
                        ? breakdownBars(job.match_breakdown) : ''}
                </div>

                <div class="detail-explain">
                    ${(job.match_reasons || []).length ? `<div class="explain-block ok">
                        <span class="explain-label">Why apply</span>
                        <ul>${job.match_reasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
                    </div>` : ''}
                    ${(job.match_gaps || []).length ? `<div class="explain-block warn">
                        <span class="explain-label">Gaps</span>
                        <ul>${job.match_gaps.map(g => `<li>${escapeHtml(g)}</li>`).join('')}</ul>
                    </div>` : ''}
                    ${(job.match_risks || []).length ? `<div class="explain-block risk">
                        <span class="explain-label">Why you might not apply</span>
                        <ul>${job.match_risks.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ul>
                    </div>` : ''}
                </div>

                <div class="detail-sponsorship">
                    <h4>Work authorization —
                        ${(SPONSORSHIP_UI[job.sponsorship_status] || SPONSORSHIP_UI.unknown).icon}
                        ${(SPONSORSHIP_UI[job.sponsorship_status] || SPONSORSHIP_UI.unknown).label}</h4>
                    <p>${escapeHtml(job.sponsorship_reason || 'No statement found in the posting.')}</p>
                    ${job.sponsorship_evidence ? `
                        <blockquote class="evidence">${escapeHtml(job.sponsorship_evidence)}</blockquote>
                        <span class="muted-note">Source: ${escapeHtml(job.sponsorship_evidence_source || 'unknown')}</span>
                    ` : '<span class="muted-note">No evidence text available.</span>'}
                </div>

                <div class="detail-actions">
                    <select id="jobStatus" class="filter-select" data-job-id="${job.id}">
                        <option value="not_applied" ${job.application_status === 'not_applied' ? 'selected' : ''}>Not Applied</option>
                        <option value="applied" ${job.application_status === 'applied' ? 'selected' : ''}>Applied</option>
                        <option value="interviewing" ${job.application_status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                        <option value="offer" ${job.application_status === 'offer' ? 'selected' : ''}>Offer</option>
                        <option value="rejected" ${job.application_status === 'rejected' ? 'selected' : ''}>Rejected</option>
                        <option value="withdrawn" ${job.application_status === 'withdrawn' ? 'selected' : ''}>Withdrawn</option>
                    </select>
                    <button class="btn btn-ghost" id="prepareFromModalBtn" data-job-id="${job.id}">
                        <i class="fas fa-wand-magic-sparkles"></i> Prepare application
                    </button>
                    <button class="btn btn-ghost" id="verifyJobBtn" data-job-id="${job.id}">
                        <i class="fas fa-link"></i> Verify link
                    </button>
                    ${job.can_apply ? `
                        <button class="btn btn-primary" id="openJobPostingBtn">
                            <i class="fas fa-external-link-alt"></i> Apply now
                        </button>` : `
                        <button class="btn" disabled title="${escapeAttr(job.can_apply_label || 'Unable to verify')}">
                            <i class="fas fa-unlink"></i> ${escapeHtml(job.can_apply_label || (job.application_url ? 'Unable to verify' : 'No apply link'))}
                        </button>`}
                </div>
                
                ${job.description ? `
                    <div class="detail-description">
                        <h4>Description</h4>
                        <p>${escapeHtml(job.description)}</p>
                    </div>
                ` : ''}
                
                <div class="detail-notes">
                    <h4>Notes</h4>
                    <textarea id="jobNotes" placeholder="Add notes about this job..." rows="3">${escapeHtml(job.notes || '')}</textarea>
                    <button class="btn btn-secondary btn-sm" id="saveJobNotesBtn" data-job-id="${job.id}">
                        <i class="fas fa-save"></i> Save Notes
                    </button>
                </div>
            </div>
            
            <style>
                .job-detail { display: flex; flex-direction: column; gap: 20px; }
                .detail-header { display: flex; align-items: center; gap: 16px; }
                .detail-header h3 { margin-bottom: 4px; }
                .detail-header p { color: var(--text-muted); font-size: 0.875rem; }
                .company-logo.large { width: 64px; height: 64px; font-size: 1.5rem; }
                .detail-info { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px 24px; }
                .info-row { display: flex; gap: 8px; }
                .info-row .label { color: var(--text-muted); }
                .detail-scores { display: flex; flex-direction: column; gap: 12px; }
                .score-summary { display: flex; gap: 8px; flex-wrap: wrap; }
                .detail-explain { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
                .detail-sponsorship { background: var(--bg-tertiary); padding: 16px; border-radius: var(--border-radius-sm); }
                .detail-sponsorship h4 { margin-bottom: 8px; }
                .detail-actions { display: flex; gap: 12px; align-items: center; }
                .detail-description { background: var(--bg-tertiary); padding: 16px; border-radius: var(--border-radius-sm); }
                .detail-description h4 { margin-bottom: 12px; }
                .detail-description p { color: var(--text-secondary); line-height: 1.6; }
                .detail-notes h4 { margin-bottom: 12px; }
                .detail-notes textarea { width: 100%; padding: 12px; background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--border-radius-sm); color: var(--text-primary); margin-bottom: 12px; resize: vertical; }
            </style>
        `;
        
        const statusSelect = document.getElementById('jobStatus');
        if (statusSelect) {
            statusSelect.addEventListener('change', (e) => {
                updateJobStatus(parseInt(statusSelect.dataset.jobId, 10), e.target.value);
            });
        }

        const openJobBtn = document.getElementById('openJobPostingBtn');
        if (openJobBtn) {
            openJobBtn.addEventListener('click', (e) =>
                openJobUrl(e, job.application_url || job.job_url || ''));
        }

        const prepareBtn = document.getElementById('prepareFromModalBtn');
        if (prepareBtn) {
            prepareBtn.addEventListener('click', () => {
                document.getElementById('jobModal').classList.remove('active');
                openPrepModal(job.id);
            });
        }

        const verifyBtn = document.getElementById('verifyJobBtn');
        if (verifyBtn) {
            verifyBtn.addEventListener('click', async () => {
                verifyBtn.disabled = true;
                verifyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking…';
                try {
                    const res = await fetchAPI(`/jobs/${job.id}/verify`, { method: 'POST' });
                    showToast(res.verification.detail,
                              res.verification.url_status === 'dead' ? 'error' : 'success');
                    openJobModal(job.id);
                } catch (err) {
                    showToast(err.message || 'Verification failed', 'error');
                    verifyBtn.disabled = false;
                    verifyBtn.innerHTML = '<i class="fas fa-link"></i> Verify link';
                }
            });
        }

        const saveNotesBtn = document.getElementById('saveJobNotesBtn');
        if (saveNotesBtn) {
            saveNotesBtn.addEventListener('click', () => {
                saveJobNotes(parseInt(saveNotesBtn.dataset.jobId, 10));
            });
        }

        document.getElementById('jobModal').classList.add('active');
    } catch (error) {
        console.error('Error opening job modal:', error);
    }
}

async function toggleFavorite(btn, jobId) {
    const isFavorited = btn.classList.contains('favorited');

    try {
        await fetchAPI(`/jobs/${jobId}`, {
            method: 'PUT',
            body: JSON.stringify({ is_favorite: !isFavorited })
        });

        btn.classList.toggle('favorited');
    } catch (error) {
        console.error('Error toggling favorite:', error);
    }
}

async function updateJobStatus(jobId, status) {
    try {
        await fetchAPI(`/jobs/${jobId}`, {
            method: 'PUT',
            body: JSON.stringify({ application_status: status })
        });
    } catch (error) {
        console.error('Error updating job status:', error);
    }
}

async function saveJobNotes(jobId) {
    const notes = document.getElementById('jobNotes').value;
    
    try {
        await fetchAPI(`/jobs/${jobId}`, {
            method: 'PUT',
            body: JSON.stringify({ notes })
        });
        alert('Notes saved!');
    } catch (error) {
        console.error('Error saving notes:', error);
    }
}

function openJobUrl(event, url) {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
    if (url) {
        window.open(url, '_blank', 'noopener,noreferrer');
    }
}

// =============================================================================
// Shared helpers
// =============================================================================

function showToast(message, tone = 'info') {
    let host = document.getElementById('toastHost');
    if (!host) {
        host = document.createElement('div');
        host.id = 'toastHost';
        host.className = 'toast-host';
        document.body.appendChild(host);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${tone}`;
    toast.textContent = message;
    host.appendChild(toast);
    setTimeout(() => toast.classList.add('visible'), 10);
    setTimeout(() => {
        toast.classList.remove('visible');
        setTimeout(() => toast.remove(), 300);
    }, 4200);
}

/** Kick off a search using the saved daily source list. */
async function startScrapeRun() {
    const checked = Array.from(
        document.querySelectorAll('input[name="source"]:checked')
    ).map(i => i.value);
    const keywords = Array.from(
        document.querySelectorAll('input[name="keyword"]:checked')
    ).map(i => i.value);
    return fetchAPI('/scrape/start', {
        method: 'POST',
        body: JSON.stringify({
            sources: checked.length ? checked : undefined,
            keywords: keywords.length ? keywords : undefined,
            min_match_score: 25,
        }),
    });
}

/** Poll scrape status until it finishes, then invoke the callback. */
function pollScrapeUntilDone(onDone) {
    const tick = async () => {
        try {
            const status = await fetchAPI('/scrape/status');
            if (status.status === 'running') {
                const progress = status.progress || {};
                const done = (progress.sources_done || []).length;
                showToastOnce(
                    `Searching… ${done}/${progress.sources_total || '?'} sources, ` +
                    `${progress.total_new_jobs || 0} new jobs`
                );
                setTimeout(tick, 2500);
                return;
            }
            if (status.status === 'failed') {
                showToast(status.error || 'Search failed', 'error');
            } else {
                const results = status.results || {};
                showToast(
                    `Search complete: ${results.total_new_jobs || 0} new jobs`, 'success'
                );
            }
            if (onDone) onDone(status);
        } catch (err) {
            setTimeout(tick, 4000);
        }
    };
    setTimeout(tick, 1500);
}

let _lastProgressToast = 0;
function showToastOnce(message) {
    const now = Date.now();
    if (now - _lastProgressToast < 9000) return;
    _lastProgressToast = now;
    showToast(message, 'info');
}

function initScraper() {
    document.getElementById('startScrape').addEventListener('click', async () => {
        const sources = Array.from(document.querySelectorAll('input[name="source"]:checked')).map(i => i.value);
        const keywords = Array.from(document.querySelectorAll('input[name="keyword"]:checked')).map(i => i.value);
        const locations = Array.from(document.querySelectorAll('input[name="location"]:checked')).map(i => i.value);
        const minMatchScore = parseInt(document.getElementById('minMatchScore')?.value || '30');
        
        if (!sources.length || !keywords.length) {
            alert('Please select at least one source and keyword');
            return;
        }
        
        const statusEl = document.getElementById('scraperStatus');
        const resultsEl = document.getElementById('scraperResults');
        const startBtn = document.getElementById('startScrape');
        
        statusEl.style.display = 'block';
        document.getElementById('statusText').textContent = 'Starting scrape in background…';
        resultsEl.style.display = 'none';
        startBtn.disabled = true;
        
        try {
            const start = await fetchAPI('/scrape/start', {
                method: 'POST',
                body: JSON.stringify({ sources, keywords, locations, min_match_score: minMatchScore })
            });

            if (start.status === 'completed' && start.results) {
                renderScrapeResults(start.results, sources, minMatchScore);
                startBtn.disabled = false;
                return;
            }

            // Poll until finished; refresh jobs periodically so new rows appear live
            let lastJobsRefresh = 0;
            const poll = async () => {
                try {
                    const st = await fetchAPI('/scrape/status');
                    const msg = st.message || 'Scraping…';
                    const prog = st.progress || {};
                    const done = (prog.sources_done || []).length;
                    const total = prog.sources_total || sources.length;
                    document.getElementById('statusText').textContent =
                        `${msg} (${done}/${total} sources · ${prog.total_new_jobs || 0} new)`;

                    const now = Date.now();
                    if (now - lastJobsRefresh > 8000) {
                        lastJobsRefresh = now;
                        try {
                            if (typeof loadJobs === 'function') await loadJobs();
                            if (typeof loadDashboard === 'function') await loadDashboard();
                        } catch (_) { /* ignore mid-scrape refresh errors */ }
                    }

                    if (st.status === 'running') {
                        setTimeout(poll, 2000);
                        return;
                    }

                    statusEl.style.display = 'none';
                    startBtn.disabled = false;

                    if (st.status === 'failed') {
                        alert('Scraping failed: ' + (st.error || st.message || 'unknown error'));
                        if (st.results) {
                            renderScrapeResults(st.results, sources, minMatchScore);
                        }
                        return;
                    }

                    const results = st.results || {
                        sources: {},
                        total_new_jobs: 0,
                        total_matched_jobs: 0,
                    };
                    renderScrapeResults(results, sources, minMatchScore);
                } catch (pollErr) {
                    console.error(pollErr);
                    document.getElementById('statusText').textContent =
                        'Waiting for scrape status… (retrying)';
                    setTimeout(poll, 3000);
                }
            };
            setTimeout(poll, 1500);
        } catch (error) {
            if (error.status === 409) {
                document.getElementById('statusText').textContent = 'Scrape already running…';
                statusEl.style.display = 'block';
                startBtn.disabled = true;
                const resume = async () => {
                    try {
                        const st = await fetchAPI('/scrape/status');
                        document.getElementById('statusText').textContent = st.message || 'Scraping…';
                        if (st.status === 'running') {
                            setTimeout(resume, 2000);
                            return;
                        }
                        statusEl.style.display = 'none';
                        startBtn.disabled = false;
                        if (st.results) renderScrapeResults(st.results, sources, minMatchScore);
                    } catch (_) {
                        setTimeout(resume, 3000);
                    }
                };
                setTimeout(resume, 1500);
                return;
            }
            statusEl.style.display = 'none';
            startBtn.disabled = false;
            alert('Error during scraping: ' + error.message);
        }
    });
}

function renderScrapeResults(results, sources, minMatchScore) {
    const statusEl = document.getElementById('scraperStatus');
    const resultsEl = document.getElementById('scraperResults');
    statusEl.style.display = 'none';
    resultsEl.style.display = 'block';

    const viewFreshJobs = () => {
        state.filters.dateFilter = 'week';
        if (sources.length === 1) {
            state.filters.source = sources[0];
            const sourceSelect = document.getElementById('sourceFilter');
            if (sourceSelect) sourceSelect.value = sources[0];
        } else {
            state.filters.source = '';
            const sourceSelect = document.getElementById('sourceFilter');
            if (sourceSelect) sourceSelect.value = '';
        }
        const dateSelect = document.getElementById('dateFilter');
        if (dateSelect) dateSelect.value = 'week';
        switchView('jobs');
    };

    document.getElementById('resultsContent').innerHTML = `
        <p><strong>Total New Jobs (${minMatchScore}%+ match):</strong> ${results.total_new_jobs || 0}</p>
        <p><strong>Total Matched Jobs:</strong> ${results.total_matched_jobs || 0}</p>
        <p><strong>Match Output Rate:</strong> ${calculateOutputRate(results)}%</p>
        <div style="margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn btn-primary" id="viewFreshJobsBtn">
                <i class="fas fa-bolt"></i>
                View Fresh Jobs (Last 7 Days)
            </button>
            <button class="btn btn-secondary" id="viewAllJobsBtn">
                <i class="fas fa-list"></i>
                View All Jobs
            </button>
        </div>
        <div style="margin-top: 12px;">
            ${Object.entries(results.sources || {}).map(([source, data]) => `
                <div style="padding: 8px; background: var(--bg-primary); border-radius: 8px; margin-bottom: 8px;">
                    <strong>${capitalizeFirst(source)}:</strong>
                    ${data.new_jobs || 0} new
                    ${data.matched_jobs != null ? `(${data.matched_jobs} matched / ${data.total_found || 0} found)` : ''}
                    ${data.error ? `<br><small style="color: var(--warning);">${escapeHtml(data.error)}</small>` : ''}
                    ${data.errors?.length ? `<br><small style="color: var(--danger);">Errors: ${data.errors.length}</small>` : ''}
                </div>
            `).join('')}
        </div>
    `;

    document.getElementById('viewFreshJobsBtn')?.addEventListener('click', (e) => {
        e.preventDefault();
        viewFreshJobs();
    });
    document.getElementById('viewAllJobsBtn')?.addEventListener('click', (e) => {
        e.preventDefault();
        state.filters.dateFilter = '';
        const dateSelect = document.getElementById('dateFilter');
        if (dateSelect) dateSelect.value = '';
        switchView('jobs');
    });

    // Auto-open fresh jobs so new data is visible without an extra click
    viewFreshJobs();
}

function initProfile() {
    document.getElementById('profileForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const data = {
            name: document.getElementById('profileName').value,
            email: document.getElementById('profileEmail').value,
            github_url: document.getElementById('profileGithub').value,
            linkedin_url: document.getElementById('profileLinkedin').value,
            target_role: document.getElementById('profileRole').value,
            resume_path: document.getElementById('profileResume').value
        };
        
        try {
            await fetchAPI('/profile', {
                method: 'PUT',
                body: JSON.stringify(data)
            });
            alert('Profile saved!');
        } catch (error) {
            console.error('Error saving profile:', error);
        }
    });

    document.getElementById('saveLocationPrefs')?.addEventListener('click', saveLocationPrefs);
}

const STATE_CHIP_POOL = [
    'MA', 'ME', 'CT', 'NJ', 'TX', 'NY', 'PA', 'MD', 'VA', 'DC',
    'NH', 'RI', 'VT', 'DE', 'NC', 'OH', 'TN', 'MN', 'AZ', 'UT', 'CO', 'IL', 'GA',
    'CA', 'WA', 'OR', 'FL', 'MI', 'WI',
];

function renderStateChips(containerId, selected) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const chosen = new Set((selected || []).map((s) => String(s).toUpperCase()));
    container.innerHTML = STATE_CHIP_POOL.map((code) => `
        <label class="state-chip ${chosen.has(code) ? 'active' : ''}">
            <input type="checkbox" value="${code}" ${chosen.has(code) ? 'checked' : ''}>
            ${code}
        </label>
    `).join('');
    container.querySelectorAll('input').forEach((input) => {
        input.addEventListener('change', () => {
            input.closest('.state-chip').classList.toggle('active', input.checked);
        });
    });
}

function selectedChips(containerId) {
    return Array.from(document.querySelectorAll(`#${containerId} input:checked`))
        .map((el) => el.value);
}

async function saveLocationPrefs() {
    const payload = {
        location_preferences: {
            preferred_states: selectedChips('prefPreferredStates'),
            acceptable_states: selectedChips('prefAcceptableStates'),
            excluded_states: selectedChips('prefExcludedStates'),
            allow_remote_us: document.getElementById('prefRemoteUs')?.checked !== false,
            allow_hybrid: document.getElementById('prefHybrid')?.checked !== false,
            allow_relocation: document.getElementById('prefRelocation')?.checked !== false,
        },
    };
    try {
        await fetchAPI('/preferences', { method: 'PUT', body: JSON.stringify(payload) });
        alert('Location preferences saved. New searches will use them.');
    } catch (error) {
        console.error('Error saving location preferences:', error);
        alert('Could not save location preferences.');
    }
}

function renderProfileLists(profile) {
    const edu = document.getElementById('profileEducation');
    if (edu) {
        const rows = profile.education || [];
        edu.innerHTML = rows.length
            ? rows.map((e) => `<div class="profile-row"><strong>${escapeHtml(e.degree || '')}</strong> ${escapeHtml(e.field || '')} — ${escapeHtml(e.school || 'Unknown')}${e.gpa != null ? ` · GPA ${e.gpa}` : ''}${e.end_date ? ` · ${escapeHtml(e.end_date)}` : ''}</div>`).join('')
            : '<p class="muted-note">No education records stored.</p>';
    }
    const skills = document.getElementById('profileSkills');
    if (skills) {
        const rows = profile.skills || [];
        skills.innerHTML = rows.length
            ? rows.map((s) => `<span class="pill">${escapeHtml(s.name)}</span>`).join('')
            : '<p class="muted-note">No skills stored.</p>';
    }
    const exp = document.getElementById('profileExperience');
    if (exp) {
        const rows = profile.experience || [];
        exp.innerHTML = rows.length
            ? rows.map((e) => `<div class="profile-row"><strong>${escapeHtml(e.title)}</strong> · ${escapeHtml(e.company || 'Unknown')}${e.location ? ` · ${escapeHtml(e.location)}` : ''}<div class="muted-note">${escapeHtml(e.description || '')}</div></div>`).join('')
            : '<p class="muted-note">No experience records stored.</p>';
    }
    const projects = document.getElementById('profileProjects');
    if (projects) {
        const rows = profile.projects || [];
        projects.innerHTML = rows.length
            ? rows.map((p) => `<div class="profile-row"><strong>${escapeHtml(p.name)}</strong><div class="muted-note">${escapeHtml(p.description || '')}</div></div>`).join('')
            : '<p class="muted-note">No projects stored. Add them in the database if you want them used in application prep — they will not be invented.</p>';
    }
}

async function loadProfile() {
    try {
        const profile = await fetchAPI('/profile');
        
        if (profile) {
            document.getElementById('profileName').value = profile.name || '';
            document.getElementById('profileEmail').value = profile.email || '';
            document.getElementById('profileGithub').value = profile.github_url || '';
            document.getElementById('profileLinkedin').value = profile.linkedin_url || '';
            document.getElementById('profileRole').value = profile.target_role || '';
            document.getElementById('profileResume').value = profile.resume_path || '';
            renderProfileLists(profile);
            const loc = (profile.preferences && profile.preferences.location_preferences) || {};
            renderStateChips('prefPreferredStates', loc.preferred_states);
            renderStateChips('prefAcceptableStates', loc.acceptable_states);
            renderStateChips('prefExcludedStates', loc.excluded_states);
            const remote = document.getElementById('prefRemoteUs');
            if (remote) remote.checked = loc.allow_remote_us !== false;
            const hybrid = document.getElementById('prefHybrid');
            if (hybrid) hybrid.checked = loc.allow_hybrid !== false;
            const reloc = document.getElementById('prefRelocation');
            if (reloc) reloc.checked = loc.allow_relocation !== false;
        }
    } catch (error) {
        console.error('Error loading profile:', error);
    }
}

async function fetchAPI(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const config = {
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    };
    
    const response = await fetch(url, config);
    let data = null;
    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }

    if (!response.ok) {
        const detail = (data && (data.error || data.message)) || `API error: ${response.status}`;
        const err = new Error(detail);
        err.status = response.status;
        err.data = data;
        throw err;
    }
    
    return data;
}

function getCompanyInitials(company) {
    if (!company) return '?';
    return company.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
}

function formatDate(dateStr) {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    
    if (hours < 1) return 'Just now';
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function capitalizeFirst(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttr(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function calculateOutputRate(results) {
    const sourceData = Object.values(results.sources || {});
    const totalFound = sourceData.reduce((sum, source) => sum + (source.total_found || 0), 0);
    if (!totalFound) return 0;
    const matched = results.total_matched_jobs || 0;
    return ((matched / totalFound) * 100).toFixed(2);
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// NUWorks Login Flow
const nuworksState = {
    isLoggedIn: false,
    isLoggingIn: false
};

function initNUWorks() {
    const startLoginBtn = document.getElementById('nuworksStartLogin');
    const checkDuoBtn = document.getElementById('nuworksCheckDuo');
    const scrapeJobsBtn = document.getElementById('nuworksScrapeJobs');
    const closeBtn = document.getElementById('nuworksClose');
    
    if (startLoginBtn) {
        startLoginBtn.addEventListener('click', startNUWorksLogin);
    }
    if (checkDuoBtn) {
        checkDuoBtn.addEventListener('click', checkNUWorksDuo);
    }
    if (scrapeJobsBtn) {
        scrapeJobsBtn.addEventListener('click', scrapeNUWorksJobs);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', closeNUWorksSession);
    }
}

async function startNUWorksLogin() {
    const username = document.getElementById('nuworksUsername').value;
    const password = document.getElementById('nuworksPassword').value;
    
    if (!username || !password) {
        updateNUWorksStatus('error', 'Please enter your Northeastern email and password');
        return;
    }
    
    const startBtn = document.getElementById('nuworksStartLogin');
    const checkDuoBtn = document.getElementById('nuworksCheckDuo');
    const closeBtn = document.getElementById('nuworksClose');
    
    startBtn.disabled = true;
    updateNUWorksStatus('waiting', 'Opening browser and entering credentials...');
    
    try {
        const result = await fetchAPI('/nuworks/login/start', {
            method: 'POST',
            body: JSON.stringify({ username, password })
        });
        
        if (result.status === 'waiting_duo') {
            updateNUWorksStatus('waiting', result.message);
            checkDuoBtn.style.display = 'inline-flex';
            closeBtn.style.display = 'inline-flex';
            nuworksState.isLoggingIn = true;
        } else if (result.status === 'error') {
            updateNUWorksStatus('error', result.message);
            startBtn.disabled = false;
        }
    } catch (error) {
        updateNUWorksStatus('error', 'Failed to start login: ' + error.message);
        startBtn.disabled = false;
    }
}

async function checkNUWorksDuo() {
    const checkDuoBtn = document.getElementById('nuworksCheckDuo');
    const scrapeJobsBtn = document.getElementById('nuworksScrapeJobs');
    const startBtn = document.getElementById('nuworksStartLogin');
    
    checkDuoBtn.disabled = true;
    updateNUWorksStatus('waiting', 'Checking login status...');
    
    try {
        const result = await fetchAPI('/nuworks/login/check');
        
        if (result.status === 'logged_in') {
            updateNUWorksStatus('success', result.message);
            nuworksState.isLoggedIn = true;
            nuworksState.isLoggingIn = false;
            checkDuoBtn.style.display = 'none';
            scrapeJobsBtn.style.display = 'inline-flex';
        } else if (result.status === 'waiting_duo') {
            updateNUWorksStatus('waiting', result.message + ' Please complete Duo authentication in the browser window.');
            checkDuoBtn.disabled = false;
        } else {
            updateNUWorksStatus('error', result.message);
            checkDuoBtn.disabled = false;
        }
    } catch (error) {
        updateNUWorksStatus('error', 'Failed to check status: ' + error.message);
        checkDuoBtn.disabled = false;
    }
}

async function scrapeNUWorksJobs() {
    const scrapeJobsBtn = document.getElementById('nuworksScrapeJobs');
    
    scrapeJobsBtn.disabled = true;
    updateNUWorksStatus('waiting', 'Scraping NUWorks jobs... This may take a few minutes.');
    
    const keywords = Array.from(document.querySelectorAll('input[name="keyword"]:checked')).map(i => i.value);
    const locations = Array.from(document.querySelectorAll('input[name="location"]:checked')).map(i => i.value);
    
    try {
        const result = await fetchAPI('/nuworks/scrape', {
            method: 'POST',
            body: JSON.stringify({ 
                keywords: keywords.length ? keywords : undefined,
                locations: locations.length ? locations : undefined
            })
        });
        
        if (result.status === 'success') {
            updateNUWorksStatus('success', `${result.message}! Refresh the dashboard to see new jobs.`);
        } else {
            updateNUWorksStatus('error', result.message);
        }
    } catch (error) {
        updateNUWorksStatus('error', 'Failed to scrape jobs: ' + error.message);
    }
    
    scrapeJobsBtn.disabled = false;
}

async function closeNUWorksSession() {
    try {
        await fetchAPI('/nuworks/close', { method: 'POST' });
        
        nuworksState.isLoggedIn = false;
        nuworksState.isLoggingIn = false;
        
        document.getElementById('nuworksStartLogin').disabled = false;
        document.getElementById('nuworksCheckDuo').style.display = 'none';
        document.getElementById('nuworksScrapeJobs').style.display = 'none';
        document.getElementById('nuworksClose').style.display = 'none';
        
        updateNUWorksStatus('success', 'NUWorks session closed');
        
        setTimeout(() => {
            document.getElementById('nuworksStatus').style.display = 'none';
        }, 2000);
    } catch (error) {
        updateNUWorksStatus('error', 'Failed to close session: ' + error.message);
    }
}

function updateNUWorksStatus(type, message) {
    const statusDiv = document.getElementById('nuworksStatus');
    const badge = document.getElementById('nuworksStatusBadge');
    const text = document.getElementById('nuworksStatusText');
    
    statusDiv.style.display = 'block';
    badge.className = 'status-badge ' + type;
    
    let icon = 'fa-spinner fa-spin';
    if (type === 'success') icon = 'fa-check-circle';
    if (type === 'error') icon = 'fa-exclamation-circle';
    if (type === 'waiting') icon = 'fa-spinner fa-spin';
    
    badge.innerHTML = `<i class="fas ${icon}"></i><span>${message}</span>`;
}
