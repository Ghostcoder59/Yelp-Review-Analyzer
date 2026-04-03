document.addEventListener('DOMContentLoaded', () => {
    async function parseApiResponse(res) {
        const contentType = res.headers.get('content-type') || '';

        if (contentType.includes('application/json')) {
            const jsonData = await res.json();
            if (!res.ok) {
                throw new Error(jsonData.error || `Request failed with status ${res.status}`);
            }
            return jsonData;
        }

        const text = await res.text();
        const shortText = (text || '').replace(/\s+/g, ' ').slice(0, 180);
        throw new Error(
            `Server returned non-JSON response (HTTP ${res.status}). ${shortText || 'Try again in a moment.'}`
        );
    }

    // Nav logic
    const navLinks = document.querySelectorAll('.nav-links li');
    const sections = document.querySelectorAll('.page-section');
    
    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            const targetId = link.getAttribute('data-target');
            sections.forEach(sec => {
                sec.classList.add('hidden');
                sec.classList.remove('fade-in');
            });
            const activeSec = document.getElementById(targetId);
            activeSec.classList.remove('hidden');
            activeSec.classList.add('fade-in');
            
            if (targetId === 'insights-section') loadInsights();
        });
    });

    // URL Analysis
    let liveChartInstance = null;
    document.getElementById('analyze-url-btn').addEventListener('click', async () => {
        const urlObj = document.getElementById('url-input').value;
        const pagesObj = document.getElementById('pages-input').value;
        if (!urlObj) return alert("Please enter a url");
        
        document.getElementById('analyze-url-btn').classList.add('hidden');
        document.getElementById('url-loader').classList.remove('hidden');
        document.getElementById('url-result-container').classList.add('hidden');

        const pageCount = Math.max(1, parseInt(pagesObj || '1', 10) || 1);
        
        try {
            const res = await fetch('/api/analyze/url', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: urlObj, pages: pageCount})
            });
            const data = await parseApiResponse(res);
            
            document.getElementById('url-total-reviews').innerText = data.total_reviews;
            document.getElementById('url-fake-percent').innerText = data.suspicious_percentage.toFixed(1) + "%";
            
            // Plot Scatter
            const ctx = document.getElementById('live-scatter-chart').getContext('2d');
            if(liveChartInstance) liveChartInstance.destroy();
            
            const scatterData = {
                datasets: [
                    {
                        label: 'Genuine',
                        data: data.reviews.filter(r => !r.is_fake).map(r => ({x: r.sentiment_score, y: r.anomaly_score})),
                        backgroundColor: '#10b981'
                    },
                    {
                        label: 'Suspicious/Fake',
                        data: data.reviews.filter(r => r.is_fake).map(r => ({x: r.sentiment_score, y: r.anomaly_score})),
                        backgroundColor: '#ef4444'
                    }
                ]
            };
            
            liveChartInstance = new Chart(ctx, {
                type: 'scatter',
                data: scatterData,
                options: {
                    responsive: true,
                    plugins: {
                        legend: { labels: { color: '#fff' } },
                        title: { display: true, text: 'Sentiment vs Anomaly Score Scatter Plot', color: '#fff' }
                    },
                    scales: {
                        x: { title: {display: true, text: 'Sentiment (-1 to 1)', color: '#fff'}, ticks: {color: '#94a3b8'} },
                        y: { title: {display: true, text: 'Anomaly Score (Lower = More suspicious)', color: '#fff'}, ticks: {color: '#94a3b8'} }
                    }
                }
            });
            
            // List Flagged
            let listHtml = '';
            data.reviews.filter(r => r.is_fake).forEach(r => {
                let reasonsStr = r.reasons.map(x => `<li>${x}</li>`).join('');
                listHtml += `
                    <div class="review-item">
                        <p><strong>Sentiment:</strong> ${r.sentiment_score.toFixed(2)} | <strong>Strength:</strong> ${Math.abs(r.anomaly_score).toFixed(3)}</p>
                        <p style="margin: 8px 0; color: #e2e8f0;">"${r.text}"</p>
                        <ul class="reasons">${reasonsStr}</ul>
                    </div>
                `;
            });
            document.getElementById('flagged-reviews-list').innerHTML = listHtml || "<p>No suspicious reviews found.</p>";
            
            document.getElementById('url-result-container').classList.remove('hidden');
            
        } catch(e) {
            alert("Failed to analyze URL: " + e.message);
        } finally {
            document.getElementById('analyze-url-btn').classList.remove('hidden');
            document.getElementById('url-loader').classList.add('hidden');
        }
    });

    // Insights Function
    let distChartInstance = null;
    let insightsLoaded = false;
    async function loadInsights() {
        if (insightsLoaded) return;
        try {
            const res = await fetch('/api/insights');
            const data = await parseApiResponse(res);
            
            document.getElementById('insight-total').innerText = data.total_reviews.toLocaleString();
            document.getElementById('insight-rating').innerText = data.average_rating.toFixed(2) + " ⭐";
            document.getElementById('insight-words').innerText = Math.round(data.average_word_count);
            
            const ctx = document.getElementById('rating-dist-chart').getContext('2d');
            const sortedLabels = Object.keys(data.rating_distribution).sort();
            const counts = sortedLabels.map(k => data.rating_distribution[k]);
            
            distChartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: sortedLabels,
                    datasets: [{
                        label: 'Number of Reviews',
                        data: counts,
                        backgroundColor: 'rgba(99, 102, 241, 0.6)',
                        borderColor: '#6366f1',
                        borderWidth: 1,
                        borderRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display:false },
                        title: { display: true, text: 'Yelp Rating Distribution (Training Baseline)', color: '#fff' }
                    },
                    scales: {
                        x: { ticks: {color: '#94a3b8'}, grid:{display:false} },
                        y: { ticks: {color: '#94a3b8'}, grid:{color:'rgba(255,255,255,0.05)'} }
                    }
                }
            });
            insightsLoaded = true;
        } catch(e) {
            console.error("Failed to load insights:", e.message);
        }
    }
});
