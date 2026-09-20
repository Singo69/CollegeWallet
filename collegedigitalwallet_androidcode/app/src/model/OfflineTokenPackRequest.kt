package com.example.collegedigitalwallet.model

data class OfflineTokenPackRequest(
    val sender_username: String,
    val pack_size: Int = 5
)