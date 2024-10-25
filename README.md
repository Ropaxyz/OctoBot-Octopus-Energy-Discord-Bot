# OctoBot: Octopus Energy Discord Bot

OctoBot is a Discord bot that integrates with the Octopus Energy API to provide users with their energy consumption data and costs directly within Discord. This bot allows users to set up their Octopus Energy accounts and retrieve detailed information about their electricity and gas usage.

## Features

- Easy account setup through Discord commands or button interactions
- Retrieval of energy consumption data for electricity and gas
- Generation of consumption charts with improved visualizations using Seaborn
- Calculation of energy costs based on consumption and tariff data
- Support for different time periods (7, 30, or 90 days)
- Secure storage of user API keys and account numbers
- Improved error handling and data validation
- Caching system for better performance
- Detailed logging system
- Automatic timezone handling
- Retry mechanism for API requests
- Rate limiting and cooldown system

## Prerequisites

- Python 3.8+
- Discord Bot Token
- Octopus Energy API access

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/Ropaxyz/OctoBot-Octopus-Energy-Discord-Bot.git
   cd OctoBot-Octopus-Energy-Discord-Bot
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the root directory with the following variables:
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   DATABASE_URL=sqlite:///user_data.db
   SETUP_CHANNEL_ID=your_channel_id_here
   ```

## Features and Improvements

### New Features
- Improved error handling with detailed logging
- Data caching system using TTLCache
- Automatic retry mechanism for failed API requests
- Enhanced visualization using Seaborn
- Combined charts for electricity and gas data
- Better date handling with timezone support
- Input validation for API keys and account numbers
- Cooldown system for commands
- Improved setup process with validation
- Warning system for potentially incomplete data

### Technical Improvements
- Modular code structure with separate classes
- Type hints and dataclasses
- Comprehensive error logging
- Better database schema with timestamps
- Configurable timeouts and retry policies
- GraphQL query optimization
- Improved API client with connection pooling

## Usage

1. Run the bot:
   ```
   python octopus_energy_bot.py
   ```

2. Invite the bot to your Discord server using the OAuth2 URL generated in the Discord Developer Portal.

3. The bot will automatically create a setup button in the configured channel.

4. Users can set up their accounts either through:
   - Clicking the setup button
   - Using the `/setup` command
   - Setting up via DM

5. Use `/get_energy_data` to retrieve energy consumption data and charts:
   - Choose between electricity, gas, or both
   - Select time period (7, 30, or 90 days)
   - View consumption charts and cost analysis

## Command Reference

### User Commands
- `/setup` - Configure your Octopus Energy account
- `/get_energy_data` - Get energy consumption data and analysis

### Admin Commands
- `!setup_button` - Create a setup button in the current channel (Admin only)

## Error Handling

The bot now includes comprehensive error handling:
- API timeouts and retry mechanism
- Invalid credentials handling
- Rate limiting protection
- Data validation
- User-friendly error messages

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This bot is not officially affiliated with Octopus Energy. Use at your own risk.

## Support

If you encounter any issues or have questions:
- [Open an issue](https://github.com/Ropaxyz/OctoBot-Octopus-Energy-Discord-Bot/issues) on GitHub
- Join our Discord server: [https://discord.gg/3ZCtSyMCp3](https://discord.gg/3ZCtSyMCp3)

## Author

[Ropaxyz](https://github.com/Ropaxyz)

Discord: ross_._
