# Aviasales Roblox Discord Bot

## Overview

This is a Discord bot for managing virtual airline operations in Roblox. The bot allows users to register airlines, create and manage flights, handle partner applications, and provide customer support through a ticket system. All data is persisted using Firebase Firestore as the database backend.

The bot is written in Python using the discord.py library with slash commands (app_commands) and features a modular cog-based architecture for organizing different functional areas.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Bot Framework
- **Discord.py with Cogs Pattern**: The bot uses discord.py's extension system (cogs) to organize functionality into separate modules:
  - `cogs/flights.py` - Flight creation, management, booking, and notifications
  - `cogs/airlines.py` - Airline registration and settings management
  - `cogs/admin.py` - Administrative panel and moderation tools
  - `cogs/partners.py` - Partner application handling
  - `cogs/support.py` - Support ticket system
  - `cogs/forms.py` - Modal forms for user input (airline registration, partner applications, support tickets)

### Command System
- Uses Discord slash commands (`app_commands`) for modern interaction
- Commands are in Russian language (e.g., `/рейс`, `/админ`, `/настройка`)
- Interactive UI components: Buttons, Views, Modals, and Select menus

### Data Layer
- **Firebase Firestore**: NoSQL document database for all persistent data
- `utils/database.py` - Database handler class with async methods for common operations
- `firebase_config.py` - Firebase initialization from environment variable
- Collections used: `airlines`, `flights`, `partners`, `airline_applications`, `support_tickets`, `subscriptions`

### Utility Modules
- `utils/embeds.py` - Helper class for creating consistent Discord embeds
- `utils/database.py` - Database abstraction layer for Firestore operations

### Error Handling Considerations
Based on attached error logs, the bot needs to handle:
- Discord interaction timeouts (3-second response limit)
- Select menu option limits (max 25 options)
- Proper use of `defer()` for long-running operations

## External Dependencies

### Core Services
- **Firebase/Firestore**: Primary database - requires `FIREBASE_CONFIG` environment secret containing service account JSON
- **Discord API**: Bot token required as environment variable

### Python Packages
- `discord.py` - Discord bot framework with slash commands support
- `firebase-admin` - Firebase SDK for Python
- `pytz` - Timezone handling for flight schedules

### Environment Variables Required
- `FIREBASE_CONFIG` - JSON string containing Firebase service account credentials
- Discord bot token (referenced in main.py but variable name not visible in provided files)