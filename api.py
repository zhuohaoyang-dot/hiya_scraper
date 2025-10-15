from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import asyncio
from scraper import HiyaScraper
import tempfile
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for GitHub Pages

@app.route('/scrape', methods=['POST'])
def scrape_hiya():
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        pages = data.get('pages', 20)
        
        # Create scraper instance
        scraper = HiyaScraper(email, password)
        scraper.total_pages = pages  # Override page limit
        
        # Run async scraper
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(scraper.scrape())
        loop.close()
        
        # Save to temporary CSV
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as tmp:
            filename = scraper.save_to_csv(tmp.name)
        
        # Send file and clean up
        response = send_file(
            filename,
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'hiya_phones_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
        
        os.unlink(filename)
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8000)