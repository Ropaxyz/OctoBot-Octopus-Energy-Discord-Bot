# -*- coding: utf-8 -*-
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import aiohttp
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import io
from dotenv import load_dotenv
import os
from gql import gql, Client
from gql.transport.aiohttp import AIOHTTPTransport
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DATABASE_URL = "sqlite:///user_data.db"

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True)
    api_key = Column(String)
    account_number = Column(String)

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# GraphQL and REST API endpoints
graphql_url = "https://api.octopus.energy/v1/graphql/"
rest_api_url = "https://api.octopus.energy/v1/"

# GraphQL queries and mutations
obtain_token_mutation = gql("""
mutation obtainKrakenToken($input: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $input) {
    token
  }
}
""")

account_query = gql("""
query Account($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    number
    properties {
      electricityMeterPoints {
        mpan
        meters {
          serialNumber
          consumptionUnits
        }
        agreements {
          validFrom
          validTo
          tariff {
            ... on TariffType {
              displayName
              productCode
            }
          }
        }
      }
      gasMeterPoints {
        mprn
        meters {
          serialNumber
          consumptionUnits
        }
        agreements {
          validFrom
          validTo
          tariff {
            ... on TariffType {
              displayName
              productCode
            }
          }
        }
      }
    }
  }
}
""")

class SetupModal(discord.ui.Modal, title="Set Up Octopus Energy Account"):
    api_key = discord.ui.TextInput(label="Octopus Energy API Key", style=discord.TextStyle.short)
    account_number = discord.ui.TextInput(label="Account Number", style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        api_key = self.api_key.value
        account_number = self.account_number.value

        session = Session()
        user = session.query(User).filter_by(discord_id=str(user_id)).first()
        if not user:
            user = User(discord_id=str(user_id))
            session.add(user)
        user.api_key = api_key
        user.account_number = account_number
        session.commit()
        session.close()

        await interaction.response.send_message("Your Octopus Energy account has been set up successfully!", ephemeral=True)

class SetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Set Up Octopus Energy Account", style=discord.ButtonStyle.primary, custom_id="setup_button")
    async def setup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("How would you like to set up your account?", view=SetupChoiceView(), ephemeral=True)

class SetupChoiceView(discord.ui.View):
    def __init__(self):
        super().__init__()

    @discord.ui.button(label="Set up via DM", style=discord.ButtonStyle.primary)
    async def dm_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("I'll send you a DM to set up your account.", ephemeral=True)
        await interaction.user.send("Let's set up your Octopus Energy account. Please use the /setup command here.")

    @discord.ui.button(label="Set up here", style=discord.ButtonStyle.secondary)
    async def channel_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SetupModal())

@bot.tree.command(name="setup", description="Set up your Octopus Energy account")
async def setup(interaction: discord.Interaction):
    await interaction.response.send_modal(SetupModal())

@bot.tree.command(name="get_energy_data", description="Get your energy consumption data")
@app_commands.choices(
    energy_type=[
        app_commands.Choice(name="Electricity", value="electricity"),
        app_commands.Choice(name="Gas", value="gas"),
        app_commands.Choice(name="Both", value="both")
    ],
    time_period=[
        app_commands.Choice(name="Last 7 days", value="7"),
        app_commands.Choice(name="Last 30 days", value="30"),
        app_commands.Choice(name="Last 90 days", value="90")
    ]
)
async def get_energy_data(interaction: discord.Interaction, energy_type: app_commands.Choice[str], time_period: app_commands.Choice[str]):
    try:
        logger.info(f"get_energy_data command called by user {interaction.user.id}")
        await interaction.response.defer()

        user_id = interaction.user.id
        session = Session()
        user = session.query(User).filter_by(discord_id=str(user_id)).first()
        session.close()

        if not user:
            await interaction.followup.send("You haven't set up your Octopus Energy account yet. Use /setup to get started.", ephemeral=True)
            return

        api_key, account_number = user.api_key, user.account_number

        to_date = datetime.now()
        from_date = to_date - timedelta(days=int(time_period.value))

        # Get token
        transport = AIOHTTPTransport(url=graphql_url)
        async with Client(transport=transport, fetch_schema_from_transport=True) as session:
            token_result = await session.execute(obtain_token_mutation, variable_values={"input": {"APIKey": api_key}})

        token = token_result['obtainKrakenToken']['token']

        # Get account info with the obtained token
        transport = AIOHTTPTransport(url=graphql_url, headers={'Authorization': f'JWT {token}'})
        async with Client(transport=transport, fetch_schema_from_transport=True) as session:
            account_result = await session.execute(account_query, variable_values={"accountNumber": account_number})

        account = account_result['account']

        energy_data = {}
        tasks = []

        for property in account['properties']:
            if energy_type.value in ['electricity', 'both']:
                for meter_point in property.get('electricityMeterPoints', []):
                    tasks.append(process_meter_point(token, 'electricity', meter_point, from_date, to_date))

            if energy_type.value in ['gas', 'both']:
                for meter_point in property.get('gasMeterPoints', []):
                    tasks.append(process_meter_point(token, 'gas', meter_point, from_date, to_date))

        results = await asyncio.gather(*tasks)

        for result in results:
            if result:
                energy_data[result['fuel_type']] = result

        # Generate and send charts
        for fuel_type, data in energy_data.items():
            if data:
                chart = generate_chart(data, fuel_type)
                await interaction.followup.send(file=discord.File(chart, f"{fuel_type}_consumption_{time_period.value}_days.png"))
                await interaction.followup.send(f"{fuel_type.capitalize()} consumption summary (Last {time_period.value} days):\n```{data['summary']}```")

        logger.info(f"get_energy_data command completed successfully for user {interaction.user.id}")
    except Exception as e:
        logger.error(f"Error in get_energy_data command: {str(e)}")
        await interaction.followup.send("An error occurred while processing your request. Please try again later.", ephemeral=True)

async def process_meter_point(token, fuel_type, meter_point, from_date, to_date):
    identifier = meter_point['mpan' if fuel_type == 'electricity' else 'mprn']
    serial_number = meter_point['meters'][0]['serialNumber']
    product_code = meter_point['agreements'][0]['tariff'].get('productCode')

    logger.info(f"Processing {fuel_type} meter point: {identifier}, Serial: {serial_number}, Product: {product_code}")

    consumption_task = get_consumption_data(token, fuel_type, identifier, serial_number, from_date, to_date)
    tariff_task = get_tariff_data(fuel_type, product_code, from_date, to_date)
    standing_charge_task = get_standing_charge(fuel_type, product_code, from_date, to_date)

    consumption_data, tariff_data, standing_charge = await asyncio.gather(consumption_task, tariff_task, standing_charge_task)

    logger.info(f"Data fetched for {fuel_type}: Consumption: {bool(consumption_data)}, Tariff: {bool(tariff_data)}, Standing Charge: {standing_charge}")

    if consumption_data and tariff_data and standing_charge is not None:
        summary = calculate_summary(fuel_type, consumption_data, tariff_data, standing_charge, from_date, to_date)
        logger.info(f"Summary calculated for {fuel_type}")
        return {
            'fuel_type': fuel_type,
            'consumption': consumption_data,
            'tariff': tariff_data,
            'standing_charge': standing_charge,
            'summary': summary
        }
    else:
        logger.warning(f"Failed to process {fuel_type} meter point. Missing data.")
    return None

async def get_consumption_data(token, fuel_type, identifier, serial_number, from_date, to_date):
    url = f"{rest_api_url}{fuel_type}-meter-points/{identifier}/meters/{serial_number}/consumption/"
    params = {
        'period_from': from_date.isoformat(),
        'period_to': to_date.isoformat(),
        'group_by': 'day'
    }
    headers = {'Authorization': f'JWT {token}'}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data['results']
    return None

async def get_tariff_data(fuel_type, product_code, from_date, to_date):
    url = f"{rest_api_url}products/{product_code}/{fuel_type}-tariffs/{'G' if fuel_type == 'gas' else 'E'}-1R-{product_code}-{'G' if fuel_type == 'gas' else 'E'}/standard-unit-rates/"
    params = {
        'period_from': from_date.isoformat(),
        'period_to': to_date.isoformat()
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data['results']
    return None

async def get_standing_charge(fuel_type, product_code, from_date, to_date):
    url = f"{rest_api_url}products/{product_code}/{fuel_type}-tariffs/{'G' if fuel_type == 'gas' else 'E'}-1R-{product_code}-{'G' if fuel_type == 'gas' else 'E'}/standing-charges/"
    params = {
        'period_from': from_date.isoformat(),
        'period_to': to_date.isoformat()
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data['results'][0]['value_inc_vat'] / 100  # Convert pence to pounds
    return None

def calculate_summary(fuel_type, consumption_data, tariff_data, standing_charge, from_date, to_date):
    total_cost = 0
    total_consumption = 0
    total_days = (to_date - from_date).days

    for day in consumption_data:
        date = datetime.fromisoformat(day['interval_start']).date()
        consumption = day['consumption']
        if fuel_type == 'gas':
            # Convert m3 to kWh (assuming calorific value of 39.5 and volume correction of 1.02264)
            consumption = consumption * 39.5 * 1.02264 / 3.6
        
        total_consumption += consumption
        
        applicable_rate = next((rate for rate in tariff_data if datetime.fromisoformat(rate['valid_from']).date() <= date), None)
        
        if applicable_rate:
            rate = applicable_rate['value_inc_vat'] / 100  # Convert pence to pounds
            cost = consumption * rate
            total_cost += cost

    total_standing_charge = standing_charge * total_days
    total_cost += total_standing_charge

    summary = f"Total {fuel_type} consumption: {total_consumption:.2f} kWh\n"
    summary += f"Total {fuel_type} unit cost: £{(total_cost - total_standing_charge):.2f}\n"
    summary += f"Total standing charge: £{total_standing_charge:.2f}\n"
    summary += f"Total {fuel_type} cost: £{total_cost:.2f}"

    return summary

def generate_chart(data, fuel_type):
    dates = [datetime.fromisoformat(day['interval_start']).date() for day in data['consumption']]
    consumption = [day['consumption'] for day in data['consumption']]
    
    plt.figure(figsize=(10, 6))
    plt.plot(dates, consumption, marker='o')
    plt.title(f'{fuel_type.capitalize()} Consumption')
    plt.xlabel('Date')
    plt.ylabel('Consumption (kWh)')
    plt.xticks(rotation=45)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return buf

@bot.command()
@commands.has_permissions(administrator=True)
async def setup_button(ctx):
    channel = bot.get_channel(1298013819188154398)
    if channel:
        view = SetupView()
        message = await channel.send("Click the button below to set up your Octopus Energy account:", view=view)
        await message.pin()
        await ctx.send("Setup button has been added and pinned in the designated channel.", ephemeral=True)
    else:
        await ctx.send("The specified channel could not be found.", ephemeral=True)

@bot.command()
@commands.is_owner()  # This ensures only the bot owner can use this command
async def sync_commands(ctx):
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"Synced {len(synced)} command(s)")
    except Exception as e:
        await ctx.send(f"An error occurred while syncing commands: {str(e)}")

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    
    # Sync commands on startup
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s) on startup")
    except Exception as e:
        logger.error(f"An error occurred while syncing commands on startup: {str(e)}")

    # Automatically add the setup button when the bot starts
    channel = bot.get_channel(1298013819188154398)
    if channel:
        # Check if there's already a pinned message with the setup button
        pinned_messages = await channel.pins()
        setup_message = next((m for m in pinned_messages if m.author == bot.user and "set up your Octopus Energy account" in m.content), None)
        
        if not setup_message:
            view = SetupView()
            message = await channel.send("Click the button below to set up your Octopus Energy account:", view=view)
            await message.pin()
            logger.info("Setup button has been automatically added and pinned.")
        else:
            logger.info("Setup button already exists in pinned messages.")
    else:
        logger.warning("The specified channel could not be found for automatic setup button creation.")

async def main():
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())