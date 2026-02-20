const API_BASE = '/api';

const state = {
    currentView: 'dashboard',
    jobs: [],
    stats: {},
    currentPage: 1,
    totalPages: 1,
    filters: {
        source: '',
        location: '',
        status: '',
        dateFilter: '',
        search: ''
    }
};

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initModals();
    initFilters();
    initScraper();
    initNUWorks();
    initProfile();
    loadDashboard();
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
        state.filters.search = e.target.value;
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
        dashboard: 'Dashboard',
        jobs: 'All Jobs',
        favorites: 'Favorites',
        applied: 'Application Tracker',
        scraper: 'Job Scraper',
        profile: 'Profile'
    };
    return titles[view] || 'Dashboard';
}

function loadCurrentView() {
    switch (state.currentView) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'jobs':
            loadJobs();
            break;
        case 'favorites':
            loadFavorites();
            break;
        case 'applied':
            loadApplied();
            break;
        case 'profile':
            loadProfile();
            break;
    }
}

async function loadDashboard() {
    try {
        const stats = await fetchAPI('/stats');
        state.stats = stats;
        
        document.getElementById('totalJobs').textContent = stats.total_jobs || 0;
        document.getElementById('newToday').textContent = stats.new_today || 0;
        document.getElementById('favoriteJobs').textContent = stats.favorite_jobs || 0;
        document.getElementById('appliedJobs').textContent = stats.applied_jobs || 0;
        
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
        ziprecruiter: '#4eac51',
        runway: '#8b5cf6',
        nuworks: '#cc0000',
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
            ...(state.filters.source && { source: state.filters.source }),
            ...(state.filters.location && { location: state.filters.location }),
            ...(state.filters.status && { status: state.filters.status }),
            ...(state.filters.dateFilter && { date_filter: state.filters.dateFilter }),
            ...(state.filters.search && { search: state.filters.search })
        });
        
        const data = await fetchAPI(`/jobs?${params}`);
        state.jobs = data.jobs || [];
        state.totalPages = data.pages || 1;
        
        renderJobList('jobsList', state.jobs);
        renderPagination();
    } catch (error) {
        console.error('Error loading jobs:', error);
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
    const container = document.getElementById(containerId);
    
    if (!jobs.length) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-briefcase"></i>
                <h3>No jobs found</h3>
                <p>Try adjusting your filters or start scraping for jobs</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = jobs.map(job => `
        <div class="job-card" data-id="${job.id}">
            <div class="company-logo">${getCompanyInitials(job.company)}</div>
            <div class="job-info">
                <div class="job-title">${escapeHtml(job.title)}</div>
                <div class="job-meta">
                    <span><i class="fas fa-building"></i> ${escapeHtml(job.company)}</span>
                    <span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(job.location || 'Remote')}</span>
                    <span><i class="fas fa-clock"></i> ${formatDate(job.date_scraped)}</span>
                </div>
            </div>
            ${job.match_score ? `<span class="match-badge ${getMatchLevel(job.match_score)}">${job.match_score}% Match</span>` : ''}
            <span class="source-badge ${job.source}">${job.source}</span>
            <div class="job-actions">
                <button class="action-btn ${job.is_favorite ? 'favorited' : ''}" 
                        onclick="toggleFavorite(event, ${job.id})" 
                        title="Favorite">
                    <i class="fas fa-star"></i>
                </button>
                <button class="action-btn" 
                        onclick="openJobUrl(event, '${escapeHtml(job.job_url)}')" 
                        title="Open Job">
                    <i class="fas fa-external-link-alt"></i>
                </button>
            </div>
        </div>
    `).join('');
    
    container.querySelectorAll('.job-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.closest('.action-btn')) {
                openJobModal(parseInt(card.dataset.id));
            }
        });
    });
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
        <div class="pipeline-job" data-id="${job.id}" onclick="openJobModal(${job.id})">
            <div class="title">${escapeHtml(job.title)}</div>
            <div class="company">${escapeHtml(job.company)}</div>
        </div>
    `).join('');
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
    document.getElementById('sourceFilter').addEventListener('change', (e) => {
        state.filters.source = e.target.value;
        state.currentPage = 1;
        loadJobs();
    });
    
    document.getElementById('locationFilter').addEventListener('change', (e) => {
        state.filters.location = e.target.value;
        state.currentPage = 1;
        loadJobs();
    });
    
    document.getElementById('dateFilter').addEventListener('change', (e) => {
        state.filters.dateFilter = e.target.value;
        state.currentPage = 1;
        loadJobs();
    });
    
    document.getElementById('statusFilter').addEventListener('change', (e) => {
        state.filters.status = e.target.value;
        state.currentPage = 1;
        loadJobs();
    });
    
    document.getElementById('clearFilters').addEventListener('click', () => {
        state.filters = { source: '', location: '', status: '', dateFilter: '', search: '' };
        state.currentPage = 1;
        document.getElementById('sourceFilter').value = '';
        document.getElementById('locationFilter').value = '';
        document.getElementById('dateFilter').value = '';
        document.getElementById('statusFilter').value = '';
        document.getElementById('globalSearch').value = '';
        loadJobs();
    });
}

function initModals() {
    const jobModal = document.getElementById('jobModal');
    const addJobModal = document.getElementById('addJobModal');
    
    document.getElementById('closeModal').addEventListener('click', () => {
        jobModal.classList.remove('active');
    });
    
    document.getElementById('closeAddModal').addEventListener('click', () => {
        addJobModal.classList.remove('active');
    });
    
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', () => {
            jobModal.classList.remove('active');
            addJobModal.classList.remove('active');
        });
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
                        <span>${formatDate(job.date_posted)}</span>
                    </div>
                    <div class="info-row">
                        <span class="label">Scraped:</span>
                        <span>${formatDate(job.date_scraped)}</span>
                    </div>
                    ${job.salary_min || job.salary_max ? `
                        <div class="info-row">
                            <span class="label">Salary:</span>
                            <span>$${job.salary_min?.toLocaleString() || '?'} - $${job.salary_max?.toLocaleString() || '?'}</span>
                        </div>
                    ` : ''}
                </div>
                
                <div class="detail-actions">
                    <select id="jobStatus" class="filter-select" onchange="updateJobStatus(${job.id}, this.value)">
                        <option value="not_applied" ${job.application_status === 'not_applied' ? 'selected' : ''}>Not Applied</option>
                        <option value="applied" ${job.application_status === 'applied' ? 'selected' : ''}>Applied</option>
                        <option value="interviewing" ${job.application_status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                        <option value="offer" ${job.application_status === 'offer' ? 'selected' : ''}>Offer</option>
                        <option value="rejected" ${job.application_status === 'rejected' ? 'selected' : ''}>Rejected</option>
                        <option value="withdrawn" ${job.application_status === 'withdrawn' ? 'selected' : ''}>Withdrawn</option>
                    </select>
                    <button class="btn btn-primary" onclick="openJobUrl(event, '${escapeHtml(job.job_url)}')">
                        <i class="fas fa-external-link-alt"></i> Open Job Posting
                    </button>
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
                    <button class="btn btn-secondary btn-sm" onclick="saveJobNotes(${job.id})">
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
                .detail-info { display: flex; gap: 24px; flex-wrap: wrap; }
                .info-row { display: flex; gap: 8px; }
                .info-row .label { color: var(--text-muted); }
                .detail-actions { display: flex; gap: 12px; align-items: center; }
                .detail-description { background: var(--bg-tertiary); padding: 16px; border-radius: var(--border-radius-sm); }
                .detail-description h4 { margin-bottom: 12px; }
                .detail-description p { color: var(--text-secondary); line-height: 1.6; }
                .detail-notes h4 { margin-bottom: 12px; }
                .detail-notes textarea { width: 100%; padding: 12px; background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--border-radius-sm); color: var(--text-primary); margin-bottom: 12px; resize: vertical; }
            </style>
        `;
        
        document.getElementById('jobModal').classList.add('active');
    } catch (error) {
        console.error('Error opening job modal:', error);
    }
}

async function toggleFavorite(event, jobId) {
    event.stopPropagation();
    const btn = event.currentTarget;
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
    event.stopPropagation();
    if (url) {
        window.open(url, '_blank');
    }
}

function initScraper() {
    document.getElementById('startScrape').addEventListener('click', async () => {
        const sources = Array.from(document.querySelectorAll('input[name="source"]:checked')).map(i => i.value);
        const keywords = Array.from(document.querySelectorAll('input[name="keyword"]:checked')).map(i => i.value);
        const locations = Array.from(document.querySelectorAll('input[name="location"]:checked')).map(i => i.value);
        const minMatchScore = parseInt(document.getElementById('minMatchScore')?.value || '40');
        
        if (!sources.length || !keywords.length) {
            alert('Please select at least one source and keyword');
            return;
        }
        
        const statusEl = document.getElementById('scraperStatus');
        const resultsEl = document.getElementById('scraperResults');
        const startBtn = document.getElementById('startScrape');
        
        statusEl.style.display = 'block';
        document.getElementById('statusText').textContent = 'Scraping jobs and matching to your profile...';
        resultsEl.style.display = 'none';
        startBtn.disabled = true;
        
        try {
            const result = await fetchAPI('/scrape/start', {
                method: 'POST',
                body: JSON.stringify({ sources, keywords, locations, min_match_score: minMatchScore })
            });
            
            statusEl.style.display = 'none';
            resultsEl.style.display = 'block';
            
            document.getElementById('resultsContent').innerHTML = `
                <p><strong>Total New Jobs (${minMatchScore}%+ match):</strong> ${result.results.total_new_jobs}</p>
                <p><strong>Total Matched Jobs:</strong> ${result.results.total_matched_jobs || 0}</p>
                <div style="margin-top: 12px;">
                    ${Object.entries(result.results.sources || {}).map(([source, data]) => `
                        <div style="padding: 8px; background: var(--bg-primary); border-radius: 8px; margin-bottom: 8px;">
                            <strong>${capitalizeFirst(source)}:</strong> 
                            ${data.new_jobs || 0} new jobs
                            ${data.matched_jobs ? `(${data.matched_jobs} matched)` : ''}
                            ${data.error ? `<br><small style="color: var(--warning);">${data.error}</small>` : ''}
                            ${data.errors?.length ? `<br><small style="color: var(--danger);">Errors: ${data.errors.length}</small>` : ''}
                        </div>
                    `).join('')}
                </div>
            `;
        } catch (error) {
            statusEl.style.display = 'none';
            alert('Error during scraping: ' + error.message);
        }
        
        startBtn.disabled = false;
    });
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
    
    if (!response.ok) {
        throw new Error(`API error: ${response.status}`);
    }
    
    return response.json();
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
