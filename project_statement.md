# Project Statement

## Project Title
**MoviesPK: A Location-Based Cinema Showtimes and Movie Information Platform**

## 1. Introduction
CineNear is a web-based information platform that helps users discover movies currently screening in cinemas near their location. Moviegoers today must visit many separate cinema websites to compare movies, showtimes, and seat availability. This project brings that information together in a single, easy-to-use interface.

## 2. Problem Statement
Cinema information is scattered across many independent websites, each with its own layout and format. Users who want to decide what to watch, where, and when have to browse several sites manually. This is time-consuming, and it is especially inconvenient when users want to compare options based on proximity, showtime, or seat availability. There is no single source that combines this information by location.

## 3. Objectives
- Provide a unified website where users can view movies screening in cinemas near them.
- Display movie details such as title, poster, genre, duration, language, rating, and synopsis.
- Show screening schedules (date, time, cinema, hall) and seat availability.
- Collect cinema data automatically, without manual entry.
- Keep the data current through scheduled, autonomous updates.
- Deliver a fast, responsive, and user-friendly experience on desktop and mobile.

## 4. Scope of the Project
**In scope:**
- A public-facing website for browsing movies and showtimes by location.
- Automated web scraping of multiple cinema websites.
- Storage of textual data and media assets in cloud services.
- A backend REST API serving data to the frontend.
- Scheduled, fully autonomous data refresh.

**Out of scope (unless added later):**
- Ticket booking or payment processing.
- User accounts and personalized recommendations.

*(Adjust these to match your plans.)*

## 5. System Description
The system has three main components.

### 5.1 Data Collection Layer (Python Scraper)
- A Python script scrapes movie details, showtimes, and seat availability from the websites of participating cinemas.
- The script runs autonomously at fixed times, for example **twice per day**, using a scheduler such as cron, GitHub Actions, or a cloud scheduler.
- Each run extracts, cleans, and normalizes the data into a common format, regardless of the source website's structure.
- Existing records are updated, new records are inserted, and outdated records (past showtimes) are removed or archived.
- Error handling and logging cover site layout changes, network failures, and missing data.

### 5.2 Data Storage Layer
- **MongoDB Atlas** stores all textual and structured data: movie details, cinema information (name, address, coordinates), showtimes, and seat availability.
- **Cloudflare R2** stores image assets such as posters and cinema images. The database holds only the URLs or keys of these images.
- Geospatial indexing in MongoDB supports efficient "cinemas near me" queries.

### 5.3 Application Layer (MERN Stack)
- **MongoDB:** the database, as described above.
- **Express.js and Node.js:** a backend REST API that handles queries such as nearby cinemas, movies by cinema, and showtimes by date.
- **React.js:** a responsive frontend that detects or accepts the user's location, then displays movies, schedules, and seat availability.

## 6. Key Features
1. Location-based discovery of nearby cinemas, through browser geolocation or manual city/area entry.
2. Detailed movie information pages.
3. Showtime listings by cinema, movie, and date.
4. Seat availability status (available or sold out).
5. Search and filters by genre, language, cinema, time, and date.
6. Automatically refreshed data, with no manual updates.
7. Fast image delivery through Cloudflare R2.

## 7. Technologies Used
| Component | Technology |
|---|---|
| Frontend | React.js |
| Backend | Node.js, Express.js |
| Database | MongoDB Atlas |
| Media storage | Cloudflare R2 |
| Data scraping | Python (e.g., Requests, BeautifulSoup, Selenium/Playwright) |
| Scheduling | Cron / cloud scheduler |

## 8. Expected Outcomes
- A functional website that gives users accurate, up-to-date movie and showtime information near them.
- A reliable automated pipeline that collects, cleans, and stores cinema data without human intervention.
- A scalable architecture that can support more cinemas and cities.

## 9. Benefits
- **For users:** saves time by combining information from many cinemas in one place, and helps them decide quickly.
- **For cinemas:** increases visibility and audience reach.
- **Technically:** shows a full-stack, cloud-based, automated data pipeline.

## 10. Conclusion
CineNear brings fragmented cinema information into a single, location-aware platform. By combining automated scraping, cloud storage, and the MERN stack, it gives moviegoers a fast and reliable way to find movies, showtimes, and seat availability near them.
