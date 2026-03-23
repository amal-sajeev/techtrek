# TechTrek -- Deployment Guide (CentOS Stream 9)

## Prerequisites

- CentOS Stream 9 server with root or sudo access
- A domain name pointed at the server (optional but recommended for SSL)

## 1. System packages

```bash
sudo dnf update -y
sudo dnf install -y python3.11 python3.11-pip python3.11-devel \
                    postgresql-server postgresql-contrib \
                    gcc libpq-devel nginx certbot python3-certbot-nginx
```

If `python3.11` is not available in the default repos:

```bash
sudo dnf install -y epel-release
sudo dnf install -y python3.11 python3.11-pip python3.11-devel
```

Verify:

```bash
python3.11 --version
```

## 2. PostgreSQL setup

Initialize and start PostgreSQL:

```bash
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql
```

Create the database and user:

```bash
sudo -u postgres psql
```

```sql
CREATE USER techtrek WITH PASSWORD 'your_strong_password_here';
CREATE DATABASE techtrek OWNER techtrek;
\q
```

Edit `pg_hba.conf` to allow password auth for the local user:

```bash
sudo vi /var/lib/pgsql/data/pg_hba.conf
```

Find the line for `local all all` and change the method from `peer` to `md5`.
Then restart PostgreSQL:

```bash
sudo systemctl restart postgresql
```

## 3. Application setup

Create a dedicated system user:

```bash
sudo useradd -r -m -s /bin/bash techtrek
```

Clone or copy the project into the home directory:

```bash
sudo -u techtrek bash
cd ~
# Either git clone or scp/rsync the project here
# Example: git clone <repo-url> techtrek_app
cd techtrek_app
```

Create a virtual environment and install dependencies:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Environment configuration

```bash
cp .env.example .env
vi .env
```

Fill in at minimum these three required values:

```
SECRET_KEY=<generate with: python3.11 -c "import secrets; print(secrets.token_hex(32))">
FIELD_ENCRYPTION_KEY=<generate with: python3.11 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
DATABASE_URL=postgresql+psycopg2://techtrek:your_strong_password_here@localhost:5432/techtrek
```

Set production-appropriate values:

```
DEBUG=0
BASE_URL=https://yourdomain.com
ADMIN_BOOTSTRAP_EMAIL=admin@yourdomain.com
```

Configure SMTP, Razorpay, Google OAuth, and company details as needed.

**Important:** back up your `FIELD_ENCRYPTION_KEY`. Losing it makes all encrypted user data (emails, names) unrecoverable.

## 5. Database migration

```bash
source venv/bin/activate
alembic stamp head    # if deploying to a fresh database
# OR
alembic upgrade head  # if upgrading an existing database
```

For a fresh deployment, you can also initialize the schema and optionally seed demo data:

```bash
python seed.py          # creates tables + sample data
# OR just create empty tables:
python -c "from app.database import Base, engine; Base.metadata.create_all(bind=engine)"
alembic stamp head
```

## 6. Systemd service

Create a service file:

```bash
sudo vi /etc/systemd/system/techtrek.service
```

```ini
[Unit]
Description=TechTrek Web Application
After=network.target postgresql.service

[Service]
User=techtrek
Group=techtrek
WorkingDirectory=/home/techtrek/techtrek_app
EnvironmentFile=/home/techtrek/techtrek_app/.env
ExecStart=/home/techtrek/techtrek_app/venv/bin/uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now techtrek
sudo systemctl status techtrek
```

View logs:

```bash
journalctl -u techtrek -f
```

## 7. Nginx reverse proxy

Create a site config:

```bash
sudo vi /etc/nginx/conf.d/techtrek.conf
```

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    client_max_body_size 20M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # SSE support
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 300s;
    }

    location /static/ {
        alias /home/techtrek/techtrek_app/app/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

Test and start:

```bash
sudo nginx -t
sudo systemctl enable --now nginx
```

## 8. SSL with Let's Encrypt

```bash
sudo certbot --nginx -d yourdomain.com
```

Certbot will modify the Nginx config to add SSL and set up auto-renewal. Verify the renewal timer:

```bash
sudo systemctl list-timers | grep certbot
```

## 9. Firewall

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

## 10. SELinux (if enforcing)

Allow Nginx to connect to the upstream app:

```bash
sudo setsebool -P httpd_can_network_connect 1
```

If serving static files from the home directory:

```bash
sudo chcon -R -t httpd_sys_content_t /home/techtrek/techtrek_app/app/static/
```

## Post-deployment checklist

- [ ] App responds at `https://yourdomain.com`
- [ ] Register with the `ADMIN_BOOTSTRAP_EMAIL` to get admin access
- [ ] Verify the admin panel at `/admin`
- [ ] Test booking flow end-to-end
- [ ] Confirm SMTP email delivery (booking confirmations, password resets)
- [ ] Back up `.env` and `FIELD_ENCRYPTION_KEY` securely
- [ ] Set up periodic database backups: `pg_dump techtrek > backup_$(date +%F).sql`
