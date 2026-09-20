package com.example.collegedigitalwallet.model

data class OfflineTokenPackResponse(
    val status: String,
    val message: String,
    val sender_username: String? = null,
    val pack_size: Int? = null,
    val ttl_hours: Int? = null,
    val tokens: List<OfflineTokenItem> = emptyList()
)