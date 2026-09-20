package com.example.collegedigitalwallet.model

data class OnlineTokenIssueRequest(
    val sender_username: String,
    val merchant_username: String,
    val amount: Double,
    val note: String? = null
)