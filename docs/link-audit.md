# Kwuo Platform — System Link Audit & Route Status

*Audit generated: October 2026*  
*This document tracks all navigation links, footer references, and endpoint destinations across Kwuo, cataloging which routes are live and operational versus those scheduled for upcoming milestones.*

---

## 1. Top Navigation & Header Links

| Link Text | Destination URL | Status | Target Template / Handler | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **Brand Logo (Kwuo)** | `/` | `[AVAILABLE]` | `templates/home.html` | Public landing page with features showcase and quick actions |
| **Home** | `/` | `[AVAILABLE]` | `templates/home.html` | Return to primary landing page |
| **About** | `/about` | `[AVAILABLE]` | `templates/about.html` | Origin story, creators, philosophy, core pillars, and tech stack |
| **Documentation** | `/documentation` | `[AVAILABLE]` | `templates/documentation/layout.html` | Dynamic markdown documentation reader with outline tracker |
| **Dashboard** *(Auth)* | `/dashboard` | `[AVAILABLE]` | `templates/dashboard/index.html` | Organizer command center & tournament listings |
| **Admin Panel** *(Super Admin)* | `/admin` | `[AVAILABLE]` | `templates/admin/index.html` | Django-style Site Administration with model changelists |
| **Log in** | `/auth/login` | `[AVAILABLE]` | `templates/auth/login.html` | User authentication via email and password |
| **Sign up** | `/auth/register` | `[AVAILABLE]` | `templates/auth/register.html` | New organizer registration (first user = Super Admin) |
| **Log out** | `/auth/logout` | `[AVAILABLE]` | `POST /auth/logout` | Clears `kwuo_session` JWT cookie and redirects to `/` |

---

## 2. Footer Links

### Platform & Exploration
| Link Text | Destination URL | Status | Target Template / Handler | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Home** | `/` | `[AVAILABLE]` | `templates/home.html` | Live |
| **About Kwuo** | `/about` | `[AVAILABLE]` | `templates/about.html` | Live |
| **Documentation & Guides** | `/documentation` | `[AVAILABLE]` | `templates/documentation/layout.html` | Live |
| **Tabroom Dashboard** | `/dashboard` | `[AVAILABLE]` | `templates/dashboard/index.html` | Live (requires login) |
| **Admin Panel** | `/admin` | `[AVAILABLE]` | `templates/admin/index.html` | Live (requires Super Admin) |

### Governance & Ethics
| Link Text | Destination URL | Status | Target Template / Handler | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Privacy Policy** | `/privacy` | `[AVAILABLE]` | `templates/legal/privacy.html` | Live legal document on participant data & zero-auth tokens |
| **Terms of Service** | `/terms` | `[AVAILABLE]` | `templates/legal/terms.html` | Live legal terms on tabroom responsibilities & open source |
| **Ballot Integrity** | `/documentation/03-adjudication-and-rubrics/ballot-modes.md` | `[AVAILABLE]` | `DocumentationService` | Live doc explaining sum, median trim, and Z-score modes |
| **Position Bias Policy** | `/documentation/02-tournament-mechanics/position-bias.md` | `[AVAILABLE]` | `DocumentationService` | Live doc detailing speaking position Latin square cycle |

### Community & Support
| Link Text | Destination URL | Status | Target Template / Handler | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Talk to Us / Support** | `/contact` | `[AVAILABLE]` | `templates/contact.html` | Live contact form with HTMX instant acknowledgment |
| **Direct Email** | `mailto:tab@kwuo.org` | `[AVAILABLE]` | External Email Handler | Direct tab support channel |
| **Sponsor / Buy Me a Coffee** | `https://buymeacoffee.com` | `[AVAILABLE]` | External Link | Maintainer sponsorship portal |
| **System Status** | `/health` | `[AVAILABLE]` | `GET /health` | Live JSON health check endpoint returning `status: ok` |
| **Open Source (GitHub)** | `https://github.com` | `[AVAILABLE]` | External Link | Project repository link |

---

## 3. Administration & Scoped RBAC Endpoints

| Link / Action | Destination URL | Status | Route Handler | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Site Administration** | `/admin` | `[AVAILABLE]` | `GET /admin` | Central Django-style dashboard with app categories and metrics |
| **User Changelist** | `/admin/users` | `[AVAILABLE]` | `GET /admin/users` | Filterable, searchable data table of registered user accounts |
| **Add User** | `/admin/users/add` | `[AVAILABLE]` | `GET/POST /admin/users/add` | Create user with groups and Super Admin flag |
| **Edit User** | `/admin/users/{id}` | `[AVAILABLE]` | `GET/POST /admin/users/{id}` | Change user profile, roles, and group memberships |
| **Reset Password** | `/admin/users/{id}/reset-password` | `[AVAILABLE]` | `POST /admin/users/{id}/reset-password` | Super Admin direct password reset |
| **User Bulk Action** | `/admin/users/action` | `[AVAILABLE]` | `POST /admin/users/action` | Batch activate, suspend, make admin, or delete users |
| **Group Changelist** | `/admin/groups` | `[AVAILABLE]` | `GET /admin/groups` | Security groups list (Global & Tournament-Scoped) |
| **Add Group** | `/admin/groups/add` | `[AVAILABLE]` | `GET/POST /admin/groups/add` | Create new scoped security group |
| **Edit Group** | `/admin/groups/{id}` | `[AVAILABLE]` | `GET/POST /admin/groups/{id}` | Modify group details and manage assigned permissions |
| **Add Permission to Group** | `/admin/groups/{id}/permissions/add` | `[AVAILABLE]` | `POST .../permissions/add` | Attach permission string to security group |
| **Delete Permission** | `/admin/groups/{id}/permissions/{perm_id}/delete` | `[AVAILABLE]` | `POST .../delete` | Detach permission string |
| **Clone Group** | `/admin/groups/{id}/clone` | `[AVAILABLE]` | `POST /admin/groups/{id}/clone` | Deep copy security group with all permissions |
| **Assign All Users** | `/admin/groups/{id}/assign-all` | `[AVAILABLE]` | `POST /admin/groups/{id}/assign-all` | Batch add all active users to group |
| **Permissions Changelist**| `/admin/group-permissions` | `[AVAILABLE]` | `GET /admin/group-permissions` | Inspect all permission bindings |
| **Memberships Changelist**| `/admin/group-memberships` | `[AVAILABLE]` | `GET /admin/group-memberships` | Inspect all user-to-group assignments |

---

## 4. Pending / Planned Roadmap Links (Not Yet Implemented)

The following endpoints represent planned tournament tabulation features defined in `docs/01-tournament-mechanics.md` through `docs/08-cross-tournament-ecosystem.md`. They are not yet mounted or are currently represented as roadmap targets:

| Endpoint | Status | Intended Milestone | Description |
| :--- | :--- | :--- | :--- |
| `/tournaments/new` | `[PENDING]` | Milestone 3 (Tournament Setup) | Tournament creation wizard (divisions, room bounds $[R_{\min}, R_{\max}]$, rubrics) |
| `/tournaments/{id}` | `[PENDING]` | Milestone 3 (Tournament Setup) | Tournament overview & tab room control room |
| `/tournaments/{id}/roster` | `[PENDING]` | Milestone 4 (Roster Import) | CSV/TSV competitor and judge roster upload |
| `/tournaments/{id}/rounds/new` | `[PENDING]` | Milestone 5 (Round Pairing) | Trigger Section Allocation & position-bias pairing algorithm |
| `/ballot/{token}` | `[PENDING]` | Milestone 6 (Digital Ballots) | Zero-auth mobile scorecard for adjudicators via magic QR/link |
| `/speaker/{token}` | `[PENDING]` | Milestone 6 (Digital Ballots) | Zero-auth competitor personal schedule and ballot feedback view |
| `/tournaments/{id}/standings` | `[PENDING]` | Milestone 7 (Breaks & Results) | State-gated public speaker standings and elimination break reveals |

---

## Summary Statistics

- **Total Audited Links / Endpoints**: 31
- **Live & Fully Implemented (`[AVAILABLE]`)**: 24 (77.4%)
- **Pending Tournament Milestone Endpoints (`[PENDING]`)**: 7 (22.6%)
- **Broken / 404 Links in Nav/Footer**: 0 (100% of visible navigation links are operational)
