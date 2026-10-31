#!/usr/bin/env python3
"""Generate Apple Podcasts feed.xml."""
import os, datetime

podcast_dir = "/Users/casper/Podcasts/M5 Morning Brief/mb-2026-10-30"
cover_url = "https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/mb-2026-10-30/cover.jpg"
m4a_url = "https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/download/mb-2026-10-30/episode_final.m4a"

ep_duration_mins = 19
ep_duration_secs = 0
ep_size = 13758260
podcast_date = datetime.datetime(2026, 10, 30, 18, 0, 0)
pub_date = podcast_date.strftime("%a, %d %b %Y %H:%M:%S +0000")

# Apple Podcasts feed XML - standard iTunes format
feed = (f'''<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     version="2.0">
  <channel>
    <title>M5 Morning Brief</title>
    <link>https://github.com/ronyoder31-maker/M5-Morning-Brief</link>
    <description>Daily technology news deep-dives covering tech, AI, and innovation.</description>
    <language>en-us</language>
    <copyright>(C) 2026 Ronny Yoder</copyright>
    <managingEditor>ronyoder31@gmail.com (Ronny Yoder)</managingEditor>
    <ttl>60</ttl>
    
    <!-- iTunes feed-level tags -->
    <itunes:author>Ronny Yoder</itunes:author>
    <itunes:type>episodic</itunes:type>
    <itunes:summary>Daily technology news deep-dives covering tech, AI, and innovation.</itunes:summary>
    <itunes:owner>
      <itunes:name>Ronny Yoder</itunes:name>
      <itunes:email>ronyoder31@gmail.com</itunes:email>
    </itunes:owner>
    <itunes:image href="{cover_url}"/>
    
    <!-- Self link -->
    <atom:link href="https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/latest/feed.xml" 
               rel="self" type="application/rss+xml" xmlns:atom="http://www.w3.org/2005/Atom"/>
    
    <!-- Episode entry -->
    <item>
      <title>M5 Morning Brief - October 30, 2026</title>
      <pubDate>{pub_date}</pubDate>
      <link>https://github.com/ronyoder31-maker/M5-Morning-Brief/releases/tag/mb-2026-10-30</link>
      <guid isPermaLink="false">mb-2026-10-30</guid>
      <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Ronny Yoder</dc:creator>
      
      <description>Today'"'"'s M5 Morning Brief covers: AWS targeting a trillion-dollar valuation, Amazon Prime Video revenue projections, Apple shipping 1.5M OLED MacBook Pros in 2027, Reddit logged-in mandate shift, Proton AI privacy overhaul, Meta Threads Friends testing, VRChat AI labeling decision, DOOM-to-Transformer benchmarks, Sony Mouthwashing film adaptation, geopolitical tech trade dynamics, and Binance market volatility.</description>
      
      <enclosure url="{m4a_url}" length="{ep_size}" type="audio/x-m4a"/>
      
      <!-- iTunes episode tags -->
      <itunes:author>Ronny Yoder</itunes:author>
      <itunes:subtitle>Daily tech news deep dive - Oct 30, 2026</itunes:subtitle>
      <itunes:description>Today'"'"'s M5 Morning Brief covers: AWS targeting a trillion-dollar valuation, Amazon Prime Video revenue projections, Apple shipping 1.5M OLED MacBook Pros in 2027, Reddit logged-in mandate shift, Proton AI privacy overhaul, Meta Threads Friends testing, VRChat AI labeling decision, DOOM-to-Transformer benchmarks, Sony Mouthwashing film adaptation, geopolitical tech trade dynamics, and Binance market volatility.</itunes:description>
      <itunes:Episode>{ep_duration_mins}:{ep_duration_secs}</itunes:Episode>
      <itunes:duration>{ep_duration_mins}:{ep_duration_secs:02d}</itunes:duration>
      <itunes:image href="{cover_url}"/>
      <content:encoded>&lt;![CDATA[Today'"'"'s M5 Morning Brief covers: AWS targeting a trillion-dollar valuation, Amazon Prime Video revenue projections, Apple shipping 1.5M OLED MacBook Pros in 2027, Reddit logged-in mandate shift, Proton AI privacy overhaul, Meta Threads Friends testing, VRChat AI labeling decision, DOOM-to-Transformer benchmarks, Sony Mouthwashing film adaptation, geopolitical tech trade dynamics, and Binance market volatility.]]&gt;</content:encoded>
    </item>
  </channel>
</rss>''')

# Write to the release dir alongside episode_final.m4a  
feed_path = podcast_dir + "/feed.xml"
with open(feed_path, "w") as f:
    f.write(feed)

print("Feed written: %s (%d bytes)" % (feed_path, len(feed.encode())))

# Verify iTunes fields
itunes_tags = ["author", "type", "summary", "owner", "image", 
               "subtitle", "description", "duration", "Episode"]
for tag in itunes_tags:
    found = "<itunes:%s" % tag in feed
    print("  itunes:%-12s %s" % (tag, "PRESENT" if found else "MISSING"))
